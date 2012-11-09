package com.google.appengine.api.taskqueue.dev;

import java.lang.reflect.Constructor;
import java.lang.reflect.InvocationTargetException;
import java.security.AccessController;
import java.security.PrivilegedAction;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Level;
import java.util.logging.Logger;

import org.quartz.Scheduler;
import org.quartz.SchedulerException;
import org.quartz.impl.StdSchedulerFactory;

import com.google.appengine.api.taskqueue.InternalFailureException;
import com.google.appengine.api.taskqueue.QueueConstants;
import com.google.appengine.api.taskqueue.TaskQueuePb;
import com.google.appengine.api.taskqueue.TaskQueuePb.TaskQueueAddRequest;
import com.google.appengine.api.urlfetch.URLFetchServicePb;
import com.google.appengine.api.urlfetch.dev.LocalURLFetchService;
import com.google.appengine.tools.development.AbstractLocalRpcService;
import com.google.appengine.tools.development.Clock;
import com.google.appengine.tools.development.LatencyPercentiles;
import com.google.appengine.tools.development.LocalRpcService;
import com.google.appengine.tools.development.LocalServerEnvironment;
import com.google.appengine.tools.development.LocalServiceContext;
import com.google.appengine.tools.development.ServiceProvider;
import com.google.apphosting.api.ApiProxy;
import com.google.apphosting.utils.config.QueueXml;
import com.google.apphosting.utils.config.QueueXmlReader;

@ServiceProvider(LocalRpcService.class)
public final class LocalTaskQueue extends AbstractLocalRpcService {
    private static final Logger logger = Logger.getLogger(LocalTaskQueue.class.getName());
    public static final String PACKAGE = "taskqueue";
    public static final String DISABLE_AUTO_TASK_EXEC_PROP = "task_queue.disable_auto_task_execution";
    public static final String QUEUE_XML_PATH_PROP = "task_queue.queue_xml_path";
    public static final String CALLBACK_CLASS_PROP = "task_queue.callback_class";
    private final Map<String, DevQueue> queues;
    private final AtomicInteger taskNameGenerator;
    private QueueXml queueXml;
    private Scheduler scheduler;
    private boolean disableAutoTaskExecution;
    private LocalServerEnvironment localServerEnvironment;
    private Clock clock;
    private LocalURLFetchService fetchService;
    private LocalTaskQueueCallback callback;

    public LocalTaskQueue() {
        this.queues = Collections.synchronizedMap(new TreeMap<String, DevQueue>());

        this.taskNameGenerator = new AtomicInteger(0);

        this.disableAutoTaskExecution = false;
    }

    public void init(LocalServiceContext context, Map<String, String> properties) {
        this.localServerEnvironment = context.getLocalServerEnvironment();
        this.clock = context.getClock();

        final String queueXmlPath = (String) properties.get("task_queue.queue_xml_path");
        QueueXmlReader reader;
        if (queueXmlPath != null) {
            reader = new QueueXmlReader(this.localServerEnvironment.getAppDir().getPath()) {
                public String getFilename() {
                    return queueXmlPath;
                }
            };
        } else
            reader = new QueueXmlReader(this.localServerEnvironment.getAppDir().getPath());

        this.queueXml = reader.readQueueXml();

        logger.log(Level.INFO, "LocalTaskQueue is initialized");
        if (Boolean.valueOf((String) properties.get("task_queue.disable_auto_task_execution")).booleanValue()) {
            this.disableAutoTaskExecution = true;
            logger.log(Level.INFO, "Automatic task execution is disabled.");
        }

        this.fetchService = new LocalURLFetchService();
        this.fetchService.init(null, new HashMap<String, String>());

        this.fetchService.setTimeoutInMs(600000);

        initializeCallback(properties);
    }

    private void initializeCallback(Map<String, String> properties) {
        String callbackOverrideClass = (String) properties.get("task_queue.callback_class");
        if (callbackOverrideClass != null) {
            try {
                this.callback = ((LocalTaskQueueCallback) newInstance(Class.forName(callbackOverrideClass)));
            }
            catch (InstantiationException e) {
                throw new RuntimeException(e);
            }
            catch (IllegalAccessException e) {
                throw new RuntimeException(e);
            }
            catch (ClassNotFoundException e) {
                throw new RuntimeException(e);
            }
        } else {
            this.callback = new UrlFetchServiceLocalTaskQueueCallback(this.fetchService);
        }
        this.callback.initialize(properties);
    }

    private static <E> E newInstance(Class<E> clazz) throws InstantiationException, IllegalAccessException {
        try {
            return clazz.newInstance();
        }
        catch (IllegalAccessException e) {
            Constructor<E> defaultConstructor;
            try {
                defaultConstructor = clazz.getDeclaredConstructor(new Class[0]);
            }
            catch (NoSuchMethodException f) {
                throw new InstantiationException("No zero-arg constructor.");
            }
            defaultConstructor.setAccessible(true);
            try {
                return defaultConstructor.newInstance(new Object[0]);
            }
            catch (InvocationTargetException g) {
                throw new RuntimeException(g);
            }
        }
    }

    void setQueueXml(QueueXml queueXml) {
        this.queueXml = queueXml;
    }

    public void start() {
        AccessController.doPrivileged(new PrivilegedAction<Object>() {
            public Object run() {
                LocalTaskQueue.this.start_();
                return null;
            }
        });
    }

    private void start_() {
        Thread shutdownHook = new Thread() {
            public void run() {
                LocalTaskQueue.this.stop();
            }
        };
        Runtime.getRuntime().addShutdownHook(shutdownHook);

        this.fetchService.start();

        UrlFetchJob.initialize(this.localServerEnvironment, this.clock);

        this.scheduler = startScheduler(this.disableAutoTaskExecution);
        String baseUrl = getBaseUrl(this.localServerEnvironment);
        String rabbitMQQueueName = "app_" + System.getProperty("APPLICATION_ID");
        RabbitMQclient client = new RabbitMQclient(rabbitMQQueueName, this.callback);

        if (this.queueXml != null) {
            for (QueueXml.Entry entry : this.queueXml.getEntries()) {
                if ("pull".equals(entry.getMode())) {
                    this.queues.put(entry.getName(), new DevPullQueue(entry, this.taskNameGenerator, this.clock));
                } else {
                    this.queues
                            .put(entry.getName(), new DevPushQueue(entry, this.taskNameGenerator, this.scheduler, baseUrl, this.clock, this.callback,client));
                }

            }

        }

        if (this.queues.get("default") == null) {
            QueueXml.Entry entry = QueueXml.defaultEntry();
            this.queues
                    .put(entry.getName(), new DevPushQueue(entry, this.taskNameGenerator, this.scheduler, baseUrl, this.clock, this.callback,client));
        }

        logger.info("Local task queue initialized with base url " + baseUrl);
    }

    static String getBaseUrl(LocalServerEnvironment localServerEnvironment) {
        return String.format("http://%s:%d", new Object[] { localServerEnvironment.getAddress(),
                Integer.valueOf(localServerEnvironment.getPort()) });
    }

    public void stop() {
        this.queues.clear();
        stopScheduler(this.scheduler);
        this.fetchService.stop();
    }

    public String getPackage() {
        return "taskqueue";
    }

    private long currentTimeMillis() {
        return this.clock.getCurrentTime();
    }

    private long currentTimeUsec() {
        return currentTimeMillis() * 1000L;
    }

    TaskQueuePb.TaskQueueServiceError.ErrorCode validateAddRequest(TaskQueuePb.TaskQueueAddRequest addRequest) {
        String taskName = addRequest.getTaskName();
        if ((taskName != null) && (taskName.length() != 0)
                && (!QueueConstants.TASK_NAME_PATTERN.matcher(taskName).matches())) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_TASK_NAME;
        }

        String queueName = addRequest.getQueueName();
        if ((queueName == null) || (queueName.length() == 0)
                || (!QueueConstants.QUEUE_NAME_PATTERN.matcher(queueName).matches())) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_QUEUE_NAME;
        }

        if (addRequest.getEtaUsec() < 0L) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_ETA;
        }

        if (addRequest.getEtaUsec() - currentTimeUsec() > getMaxEtaDeltaUsec()) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_ETA;
        }

        if (addRequest.getMode() == TaskQueuePb.TaskQueueMode.Mode.PULL.getValue()) {
            return validateAddPullRequest(addRequest);
        }
        return validateAddPushRequest(addRequest);
    }

    TaskQueuePb.TaskQueueServiceError.ErrorCode validateAddPullRequest(TaskQueuePb.TaskQueueAddRequest addRequest) {
        if (!addRequest.hasBody()) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_REQUEST;
        }
        return TaskQueuePb.TaskQueueServiceError.ErrorCode.OK;
    }

    TaskQueuePb.TaskQueueServiceError.ErrorCode validateAddPushRequest(TaskQueuePb.TaskQueueAddRequest addRequest) {
        String url = addRequest.getUrl();
        if ((!addRequest.hasUrl()) || (url.length() == 0) || (url.charAt(0) != '/')
                || (url.length() > QueueConstants.maxUrlLength())) {
            return TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_URL;
        }
        return TaskQueuePb.TaskQueueServiceError.ErrorCode.OK;
    }

    static long getMaxEtaDeltaUsec() {
        return QueueConstants.getMaxEtaDeltaMillis() * 1000L;
    }

    @LatencyPercentiles(latency50th = 4)
    public TaskQueuePb.TaskQueueAddResponse add(LocalRpcService.Status status, TaskQueuePb.TaskQueueAddRequest addRequest) {
        TaskQueuePb.TaskQueueBulkAddRequest bulkRequest = new TaskQueuePb.TaskQueueBulkAddRequest();
        TaskQueuePb.TaskQueueAddResponse addResponse = new TaskQueuePb.TaskQueueAddResponse();

        bulkRequest.addAddRequest().copyFrom(addRequest);
        TaskQueuePb.TaskQueueBulkAddResponse bulkResponse = bulkAdd(status, bulkRequest);

        if (bulkResponse.taskResultSize() != 1) {
            throw new InternalFailureException(String.format("expected 1 result from BulkAdd(), got %d", new Object[] { Integer
                    .valueOf(bulkResponse.taskResultSize()) }));
        }

        int result = bulkResponse.getTaskResult(0).getResult();

        if (result != TaskQueuePb.TaskQueueServiceError.ErrorCode.OK.getValue())
            throw new ApiProxy.ApplicationException(result);
        if (bulkResponse.getTaskResult(0).hasChosenTaskName()) {
            addResponse.setChosenTaskName(bulkResponse.getTaskResult(0).getChosenTaskName());
        }

        return addResponse;
    }

    @LatencyPercentiles(latency50th = 3)
    public TaskQueuePb.TaskQueuePurgeQueueResponse purgeQueue(LocalRpcService.Status status, TaskQueuePb.TaskQueuePurgeQueueRequest purgeQueueRequest) {
        TaskQueuePb.TaskQueuePurgeQueueResponse purgeQueueResponse = new TaskQueuePb.TaskQueuePurgeQueueResponse();
        flushQueue(purgeQueueRequest.getQueueName());
        return purgeQueueResponse;
    }

    @LatencyPercentiles(latency50th = 4)
    public TaskQueuePb.TaskQueueBulkAddResponse bulkAdd(LocalRpcService.Status status, TaskQueuePb.TaskQueueBulkAddRequest bulkAddRequest) {
        TaskQueuePb.TaskQueueBulkAddResponse bulkAddResponse = new TaskQueuePb.TaskQueueBulkAddResponse();
        
        System.out.println("executing bulk add");

        if (bulkAddRequest.addRequestSize() == 0) {
            return bulkAddResponse;
        }

        bulkAddRequest = (TaskQueuePb.TaskQueueBulkAddRequest) bulkAddRequest.clone();
        DevQueue queue = getQueueByName(bulkAddRequest.getAddRequest(0).getQueueName());

        Map<TaskQueuePb.TaskQueueBulkAddResponse.TaskResult, String> chosenNames = new IdentityHashMap<TaskQueuePb.TaskQueueBulkAddResponse.TaskResult, String>();

        boolean errorFound = false;

        for (TaskQueuePb.TaskQueueAddRequest addRequest : bulkAddRequest.addRequests()) {
            TaskQueuePb.TaskQueueBulkAddResponse.TaskResult taskResult = bulkAddResponse.addTaskResult();
            TaskQueuePb.TaskQueueServiceError.ErrorCode error = validateAddRequest(addRequest);
            if (error == TaskQueuePb.TaskQueueServiceError.ErrorCode.OK) {
                if ((!addRequest.hasTaskName()) || (addRequest.getTaskName().equals(""))) {
                    addRequest = addRequest.setTaskName(queue.genTaskName());
                    chosenNames.put(taskResult, addRequest.getTaskName());
                }

                taskResult.setResult(TaskQueuePb.TaskQueueServiceError.ErrorCode.SKIPPED.getValue());
            } else {
                taskResult.setResult(error.getValue());
                errorFound = true;
            }
        }

        if (errorFound) {
            return bulkAddResponse;
        }

        if (bulkAddRequest.getAddRequest(0).hasTransaction()) {
            try {
                ApiProxy.makeSyncCall("datastore_v3", "addActions", bulkAddRequest.toByteArray());
            }
            catch (ApiProxy.ApplicationException exception) {
                throw new ApiProxy.ApplicationException(exception.getApplicationError()
                        + TaskQueuePb.TaskQueueServiceError.ErrorCode.DATASTORE_ERROR.getValue(), exception.getErrorDetail());
            }
        } else {
            for (int i = 0; i < bulkAddRequest.addRequestSize(); i++) {
                TaskQueuePb.TaskQueueAddRequest addRequest = bulkAddRequest.getAddRequest(i);
                TaskQueuePb.TaskQueueBulkAddResponse.TaskResult taskResult = bulkAddResponse.getTaskResult(i);
                try {
                    queue.add(addRequest);
                }
                catch (ApiProxy.ApplicationException exception) {
                    taskResult.setResult(exception.getApplicationError());
                }
            }
        }

        for (TaskQueuePb.TaskQueueBulkAddResponse.TaskResult taskResult : bulkAddResponse.taskResults()) {
            if (taskResult.getResult() == TaskQueuePb.TaskQueueServiceError.ErrorCode.SKIPPED.getValue()) {
                taskResult.setResult(TaskQueuePb.TaskQueueServiceError.ErrorCode.OK.getValue());
                if (chosenNames.containsKey(taskResult)) {
                    taskResult.setChosenTaskName((String) chosenNames.get(taskResult));
                }
            }
        }

        return bulkAddResponse;
    }

    public TaskQueuePb.TaskQueueDeleteResponse delete(LocalRpcService.Status status, TaskQueuePb.TaskQueueDeleteRequest request) {
        String queueName = request.getQueueName();

        DevQueue queue = getQueueByName(queueName);
        TaskQueuePb.TaskQueueDeleteResponse response = new TaskQueuePb.TaskQueueDeleteResponse();
        for (String taskName : request.taskNames()) {
            try {
                if (!queue.deleteTask(taskName))
                    response.addResult(TaskQueuePb.TaskQueueServiceError.ErrorCode.UNKNOWN_TASK.getValue());
                else
                    response.addResult(TaskQueuePb.TaskQueueServiceError.ErrorCode.OK.getValue());
            }
            catch (ApiProxy.ApplicationException e) {
                response.addResult(e.getApplicationError());
            }
        }
        return response;
    }

    @LatencyPercentiles(latency50th = 8)
    public TaskQueuePb.TaskQueueQueryAndOwnTasksResponse queryAndOwnTasks(LocalRpcService.Status status, TaskQueuePb.TaskQueueQueryAndOwnTasksRequest request) {
        String queueName = request.getQueueName();
        validateQueueName(queueName);

        DevQueue queue = getQueueByName(queueName);

        if (queue.getMode() != TaskQueuePb.TaskQueueMode.Mode.PULL) {
            throw new ApiProxy.ApplicationException(TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_QUEUE_MODE.getValue());
        }

        DevPullQueue pullQueue = (DevPullQueue) queue;
        List<TaskQueuePb.TaskQueueAddRequest> results = pullQueue.queryAndOwnTasks(request.getLeaseSeconds(), request
                .getMaxTasks(), request.isGroupByTag(), request.getTagAsBytes());

        TaskQueuePb.TaskQueueQueryAndOwnTasksResponse response = new TaskQueuePb.TaskQueueQueryAndOwnTasksResponse();
        for (TaskQueuePb.TaskQueueAddRequest task : results) {
            TaskQueuePb.TaskQueueQueryAndOwnTasksResponse.Task responseTask = response.addTask();
            responseTask.setTaskName(task.getTaskName());
            responseTask.setBodyAsBytes(task.getBodyAsBytes());
            responseTask.setEtaUsec(task.getEtaUsec());
            if (task.hasTag()) {
                responseTask.setTagAsBytes(task.getTagAsBytes());
            }

        }

        return response;
    }

    public TaskQueuePb.TaskQueueModifyTaskLeaseResponse modifyTaskLease(LocalRpcService.Status status, TaskQueuePb.TaskQueueModifyTaskLeaseRequest request) {
        String queueName = request.getQueueName();
        validateQueueName(queueName);

        String taskName = request.getTaskName();
        validateTaskName(taskName);

        DevQueue queue = getQueueByName(queueName);

        if (queue.getMode() != TaskQueuePb.TaskQueueMode.Mode.PULL) {
            throw new ApiProxy.ApplicationException(TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_QUEUE_MODE.getValue());
        }

        DevPullQueue pullQueue = (DevPullQueue) queue;

        return pullQueue.modifyTaskLease(request);
    }

    public Map<String, QueueStateInfo> getQueueStateInfo() {
        TreeMap<String, QueueStateInfo> queueStateInfo = new TreeMap<String, QueueStateInfo>();

        for (Map.Entry<String, DevQueue> entry : this.queues.entrySet()) {
            String queueName = entry.getKey();
            queueStateInfo.put(queueName, entry.getValue().getStateInfo());
        }

        return queueStateInfo;
    }

    private DevQueue getQueueByName(String queueName) {
        DevQueue queue = (DevQueue) this.queues.get(queueName);
        if (queue == null) {
            throw new ApiProxy.ApplicationException(TaskQueuePb.TaskQueueServiceError.ErrorCode.UNKNOWN_QUEUE.getValue(), queueName);
        }
        return queue;
    }

    @LatencyPercentiles(latency50th = 4)
    public void flushQueue(String queueName) {
        DevQueue queue = getQueueByName(queueName);
        queue.flush();
    }

    public boolean deleteTask(String queueName, String taskName) {
        DevQueue queue = getQueueByName(queueName);
        return queue.deleteTask(taskName);
    }

    static Scheduler startScheduler(boolean disableAutoTaskExecution) {
        try {
            Scheduler scheduler = StdSchedulerFactory.getDefaultScheduler();

            if (!disableAutoTaskExecution) {
                scheduler.start();
            }
            return scheduler;
        }
        catch (SchedulerException e) {
            throw new RuntimeException(e);
        }
    }

    static void stopScheduler(Scheduler scheduler) {
        try {
            scheduler.shutdown(false);
        }
        catch (SchedulerException e) {
            throw new RuntimeException(e);
        }
    }

    public boolean runTask(String queueName, String taskName) {
        DevQueue queue = getQueueByName(queueName);
        System.out.println("calling run task in LocalTaskQueue");
        System.out.println("queue name: " + queueName);
        System.out.println("task name: " + taskName);
        return queue.runTask(taskName);
    }

    public Double getMaximumDeadline(boolean isOfflineRequest) {
        return Double.valueOf(30.0D);
    }

    static final void validateQueueName(String queueName) throws ApiProxy.ApplicationException {
        if ((queueName == null) || (queueName.length() == 0)
                || (!QueueConstants.QUEUE_NAME_PATTERN.matcher(queueName).matches())) {
            throw new ApiProxy.ApplicationException(TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_QUEUE_NAME.getValue());
        }
    }

    static final void validateTaskName(String taskName) throws ApiProxy.ApplicationException {
        if ((taskName == null) || (taskName.length() == 0)
                || (!QueueConstants.TASK_NAME_PATTERN.matcher(taskName).matches())) {
            throw new ApiProxy.ApplicationException(TaskQueuePb.TaskQueueServiceError.ErrorCode.INVALID_TASK_NAME.getValue());
        }
    }

    static final class UrlFetchServiceLocalTaskQueueCallback implements LocalTaskQueueCallback {
        /**
         * 
         */
        private static final long serialVersionUID = 1L;
        private final LocalURLFetchService fetchService;

        UrlFetchServiceLocalTaskQueueCallback(LocalURLFetchService fetchService) {
            this.fetchService = fetchService;
        }

        public int execute(URLFetchServicePb.URLFetchRequest fetchReq) {
            LocalRpcService.Status status = new LocalRpcService.Status();
            System.out.println("executing urlFetchRequest");
            return this.fetchService.fetch(status, fetchReq).getStatusCode();
        }

        public void initialize(Map<String, String> properties) {
        }
    }

    private void runAppScaleTask(final TaskQueueAddRequest addRequest) {
        AccessController.doPrivileged(new PrivilegedAction<Object>() {
            public Object run() {
                System.out.println("running appscale task!");
                new AppScaleRunTask(addRequest).run();
                return null;
            }
        });
    }
}