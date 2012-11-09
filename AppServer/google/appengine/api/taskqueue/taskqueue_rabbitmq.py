#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Rabbitmq version of the Task Queue API.

As well as implementing Task Queue API functions, the stub exposes various other
functions that are used by the dev_appserver's admin console to display the
application's queues and tasks.
"""

from __future__ import with_statement

__all__ = []
import base64
import bisect
import calendar
import cgi
import datetime
import httplib
import logging
import os
import random
import socket
import string
import threading
import time
import simplejson as json

import taskqueue_service_pb
import taskqueue

from google.appengine.api import api_base_pb
from google.appengine.api import apiproxy_stub
from google.appengine.api import apiproxy_stub_map
from google.appengine.api import queueinfo
from google.appengine.runtime import apiproxy_errors
from google.appengine.api import datastore
from google.appengine.api import datastore_errors
import pika

#TODO document these globals
DEFAULT_RATE = '5.00/s'

DEFAULT_RATE_FLOAT = 5.0

DEFAULT_BUCKET_SIZE = 5

MAX_ETA = datetime.timedelta(days=30)

MAX_PULL_TASK_SIZE_BYTES = 2 ** 20

MAX_PUSH_TASK_SIZE_BYTES = 100 * (2 ** 10)

MAX_TASK_SIZE = MAX_PUSH_TASK_SIZE_BYTES

MAX_REQUEST_SIZE = 32 << 20

MAX_RETRIES = 10

# Max wait in seconds
MAX_WAIT = 60 

# Max for time for exponential backoff for RabbitMQ reconnect
MAX_RECONNECT_TIME = 1024

BUILT_IN_HEADERS = set(['x-appengine-queuename',
                        'x-appengine-taskname',
                        'x-appengine-taskretrycount',
                        'x-appengine-development-payload',
                        'content-length'])

DEFAULT_QUEUE_NAME = 'default'

QUEUE_MODE = taskqueue_service_pb.TaskQueueMode

AUTOMATIC_QUEUES = {
    DEFAULT_QUEUE_NAME: (0.2, DEFAULT_BUCKET_SIZE, DEFAULT_RATE),
    '__cron': (1, 1, '1/s')}

_TASKQUEUE_KIND = "___TaskQueue___"
     
def _GetAppId(request):
  """Returns the app id to use for the given request.
  Args:
    request: A protocol buffer that has an app_id field.
  Returns:
    A string containing the app id or None if no app id was specified.
  """
  if request.has_app_id():
    return request.app_id()
  else:
    return None

def _SecToUsec(t):
  """Converts a time in seconds since the epoch to usec since the epoch.
  Args:
    t: Time in seconds since the unix epoch

  Returns:
    An integer containing the number of usec since the unix epoch.
  """
  return int(t * 1e6)

def _UsecToSec(t):
  """Converts a time in usec since the epoch to seconds since the epoch.

  Args:
    t: Time in usec since the unix epoch

  Returns:
    A float containing the number of seconds since the unix epoch.
  """
  return t / 1e6

def _FormatEta(eta_usec):
  """Formats a task ETA as a date string in UTC."""
  eta = datetime.datetime.utcfromtimestamp(_UsecToSec(eta_usec))
  return eta.strftime('%Y/%m/%d %H:%M:%S')

def _TruncDelta(timedelta):
  """Strips the microseconds field from a timedelta.

  Args:
    timedelta: a datetime.timedelta.

  Returns:
    A datetime.timedelta with the microseconds field not filled.
  """
  return datetime.timedelta(days=timedelta.days, seconds=timedelta.seconds)

def _EtaDelta(eta_usec, now):
  """Formats a task ETA as a relative time string."""
  eta = datetime.datetime.utcfromtimestamp(_UsecToSec(eta_usec))
  if eta > now:
    return '%s from now' % _TruncDelta(eta - now)
  else:
    return '%s ago' %  _TruncDelta(now - eta)


def QueryTasksResponseToDict(queue_name, task_response, now, secret_hash):
  """Converts a TaskQueueQueryTasksResponse_Task protobuf group into a dict.

  Args:
    queue_name: The name of the queue this task came from.
    task_response: An instance of TaskQueueQueryTasksResponse_Task.
    now: A datetime.datetime object containing the current time in UTC.

  Returns:
    A dict containing the fields used by the dev appserver's admin console.

  Raises:
    ValueError: A task response contains an unknown HTTP method type.
  """
  task = {}

  task['name'] = task_response.task_name()
  task['queue_name'] = queue_name
  task['url'] = task_response.url()
  method = task_response.method()
  if method == taskqueue_service_pb.TaskQueueQueryTasksResponse_Task.GET:
    task['method'] = 'GET'
  elif method == taskqueue_service_pb.TaskQueueQueryTasksResponse_Task.POST:
    task['method'] = 'POST'
  elif method == taskqueue_service_pb.TaskQueueQueryTasksResponse_Task.HEAD:
    task['method'] = 'HEAD'
  elif method == taskqueue_service_pb.TaskQueueQueryTasksResponse_Task.PUT:
    task['method'] = 'PUT'
  elif method == taskqueue_service_pb.TaskQueueQueryTasksResponse_Task.DELETE:
    task['method'] = 'DELETE'
  else:
    raise ValueError('Unexpected method: %d' % method)

  task['eta'] = _FormatEta(task_response.eta_usec())
  task['eta_usec'] = task_response.eta_usec()
  task['eta_delta'] = _EtaDelta(task_response.eta_usec(), now)
  task['body'] = base64.b64encode(task_response.body())
  headers = [(header.key(), header.value())
             for header in task_response.header_list()
             if header.key().lower() not in BUILT_IN_HEADERS]

  headers.append(('X-AppEngine-QueueName', queue_name))
  headers.append(('X-AppEngine-TaskName', task_response.task_name()))
  headers.append(('X-AppEngine-TaskRetryCount',
                  str(task_response.retry_count())))
  headers.append(('X-AppEngine-Development-Payload', secret_hash))
  headers.append(('Content-Length', str(len(task['body']))))
  if 'content-type' not in frozenset(key.lower() for key, _ in headers):
    headers.append(('Content-Type', 'application/octet-stream'))
  task['headers'] = headers

  return task

def _GetRandomString():
  return ''.join(random.choice(string.ascii_uppercase + string.digits) \
                    for x in range(32))

def _ChooseTaskName():
  """Returns a string containing a unique task name."""
  return 'task%s' % _GetRandomString()

def _VerifyTaskQueueAddRequest(request, now):
  """Checks that a TaskQueueAddRequest is valid.

  Checks that a TaskQueueAddRequest specifies a valid eta and a valid queue.

  Args:
    request: The taskqueue_service_pb.TaskQueueAddRequest to validate.
    now: A datetime.datetime object containing the current time in UTC.

  Returns:
    A taskqueue_service_pb.TaskQueueServiceError indicating any problems with
    the request or taskqueue_service_pb.TaskQueueServiceError.OK if it is
    valid.
  """
  if request.eta_usec() < 0:
    return taskqueue_service_pb.TaskQueueServiceError.INVALID_ETA

  eta = datetime.datetime.utcfromtimestamp(_UsecToSec(request.eta_usec()))
  max_eta = now + MAX_ETA
  if eta > max_eta:
    return taskqueue_service_pb.TaskQueueServiceError.INVALID_ETA

  queue_name_response = taskqueue_service_pb.TaskQueueServiceError.OK
  if not request.queue_name():
      queue_name_response = taskqueue_service_pb.TaskQueueServiceError.INVALID_QUEUE_NAME
  if queue_name_response != taskqueue_service_pb.TaskQueueServiceError.OK:
    return queue_name_response

  if request.has_crontimetable() and _GetAppId(request) is None:
    return taskqueue_service_pb.TaskQueueServiceError.PERMISSION_DENIED

  if request.mode() == QUEUE_MODE.PULL:
    max_task_size_bytes = MAX_PULL_TASK_SIZE_BYTES
  else:
    max_task_size_bytes = MAX_PUSH_TASK_SIZE_BYTES

  if request.ByteSize() > max_task_size_bytes:
    return taskqueue_service_pb.TaskQueueServiceError.TASK_TOO_LARGE

  return taskqueue_service_pb.TaskQueueServiceError.OK

class TaskStates:
  Running = "Running"
  Tombstoned = "Tombstoned"
  Failed = "Failed" 

class _TaskExecutor(object):
  """Executor for a task object.

  Converts a TaskQueueQueryTasksResponse_Task into a http request, then uses the
  httplib library to send it to the http server.
  """

  def __init__(self, default_host, secret_hash):
    """Constructor.

    Args:
      default_host: a string to use as the host/port to connect to if the host
          header is not specified in the task.
    """
    self._default_host = default_host
    self._secret_hash = secret_hash

  def _HeadersFromTask(self, task):
    """Constructs the http headers for the given task.

    This function will remove special headers (values in BUILT_IN_HEADERS) and
    add the taskqueue headers.

    Args:
      task: The task, a TaskQueueQueryTasksResponse_Task instance.
      queue: The queue that this task belongs to, an _Queue instance.

    Returns:
      A tuple of (header_dict, headers), where:
        header_dict: A mapping from lowercase header name to a list of values.
        headers: a list of tuples containing the http header and value. There
            may be be mutiple entries with the same key.
    """
    headers = []
    header_dict = {}
    for key, value in task['headers']:
      header_key_lower = key.lower()
      if header_key_lower not in BUILT_IN_HEADERS:
        headers.append((key, value))
        header_dict.setdefault(header_key_lower, []).append(value)

    headers.append(('X-AppEngine-QueueName', task['queue_name']))
    headers.append(('X-AppEngine-TaskName', task['name']))
    headers.append(('X-AppEngine-TaskRetryCount', '0'))
    # TODO fix this security hole
    headers.append(('X-AppEngine-Fake-Is-Admin', self._secret_hash))
    headers.append(('Content-Length', str(len(base64.b64decode(task['body'])))))
    if 'content-type' not in header_dict:
      headers.append(('Content-Type', 'application/octet-stream'))

    return header_dict, headers

  def ExecuteTask(self, task):
    """Construct a http request from the task and dispatch it.

    Args:
      task: The task to convert to a http request and then send. An instance of
          taskqueue_service_pb.TaskQueueQueryTasksResponse_Task
      queue: The queue that this task belongs to. An instance of _Queue.

    Returns:
      If the task was successfully executed.
    """
    try:
      method = task['method']
      header_dict, headers = self._HeadersFromTask(task)
      
      #connection_host, = header_dict.get('host', [self._default_host])
      connection_host = self._default_host
      if connection_host is None:
        logging.error('Could not determine where to send the task "%s" '
                      '(Url: "%s") in queue "%s". Treating as an error.',
                      task['name'], task['url'], task['queue_name'])
        return False
      connection = httplib.HTTPConnection(connection_host)

      connection.putrequest(
          method, task['url'],
          skip_host='host' in header_dict,
          skip_accept_encoding='accept-encoding' in header_dict)
      for header_key, header_value in headers:
        connection.putheader(header_key, header_value)
      connection.endheaders()
      if task["body"]:
        connection.send(base64.b64decode(task['body']))

      response = connection.getresponse()
      response.read()
      response.close()

      return 200 <= response.status < 300
    except (httplib.HTTPException, socket.error):
      logging.exception('An error occured while sending the task "%s" '
                        '(Url: "%s") in queue "%s". Treating as a task error.',
                        task['name'], task['url'], task['queue_name'])
      return False


class _BackgroundTaskScheduler(object):
  """The task scheduler class.

  This class is designed to be run in a background thread.

  Note: There must not be more than one instance of _BackgroundTaskScheduler per
  group.
  """

  def __init__(self, task_executor, app_name, retry_seconds, **kwargs):
    """Constructor.

    Args:
      task_executor: The class used to convert a task into a http request. Must
          be an instance of _TaskExecutor.
      retry_seconds: The number of seconds to delay a task by if its execution
          fails.
    """
    self._should_exit = False
    self.task_executor = task_executor
    self.default_retry_seconds = retry_seconds
    try:
      self.connection = pika.BlockingConnection(pika.ConnectionParameters(
        host='localhost'))
      self.channel = self.connection.channel()
    except pika.exceptions.AMQPConnectionError, e:
      logging.error("Unable to connect to RabbitMQ: " + str(e))
    except Exception, e:
      logging.error("Unknown Exception--unable to connect to RabbitMQ: " + str(e))
    self._queue_name = "app_%s"%app_name
    if kwargs:
      raise TypeError('Unknown parameters: %s' % ', '.join(kwargs))

  def UpdateNextEventTime(self, next_event_time):
    """Notify the TaskExecutor of the closest event it needs to process.

    Args:
      next_event_time: The time of the event in seconds since the epoch.
    """
    with self._wakeup_lock:
      if next_event_time < self._next_wakeup:
        self._next_wakeup = next_event_time
        self._event.set()
  
  def _backoff(self, task):
    """ Backoff time based on how many retries thus far
    """
    for index, header in enumerate(task["headers"]):
      if header[0].lower() == "x-appengine-taskretrycount":
        current_attempts = int(task["headers"][index][1])
        sleep_time = pow(current_attempts,2)
        if sleep_time != 0: 
          logging.info("Task %s is going to backoff for %d seconds"%(task['name'],sleep_time))
          time.sleep(sleep_time)

  def Shutdown(self):
    """Request this TaskExecutor to exit."""
    self._should_exit = True
    self._event.set()

  def _TaskCallback(self, ch, method, properties, body):
    logging.info("TaskQueue: Received %r"%(body,))
    try:
      task = json.loads(body)
    except Exception, e:
      logging.error("Exception parsing task json %s"%body)
      ch.basic_reject(delivery_tag = method.delivery_tag, requeue = False)
      return

    self._backoff(task)
    task_result = self.task_executor.ExecuteTask(task)
 
    if task_result:
      ch.basic_ack(delivery_tag = method.delivery_tag) 
      entity = datastore.Entity(_TASKQUEUE_KIND,
                                name=str(task['name']), namespace='')
      entity.update({'state': TaskStates.Tombstoned, 'name': task['name']})
      datastore.Put(entity)
    else:
      # Figure out how many attempts have been done thus far
      current_attemps = 0
      for index, header in enumerate(task["headers"]):
        if header[0].lower() == "x-appengine-taskretrycount":
          current_attempts = int(task["headers"][index][1])
          task["headers"][index][1] = str(int(current_attempts) + 1)
          logging.info("Task %s has tried %d times"%(task['name'], int(task["headers"][index][1])))
      # Too many retries
      if int(current_attempts) > MAX_RETRIES:
        ch.basic_reject(delivery_tag = method.delivery_tag, requeue = False)
        logging.warning(
            'Task %s failed to execute. The task has no remaining retries. '% task['name'] )
        entity = datastore.Entity(_TASKQUEUE_KIND,
                                name=str(task['name']), namespace='')
        entity.update({'state': TaskStates.Failed, 'name': task['name']})
        datastore.Put(entity)
      else: # Reinqueue with updated number of tries
        logging.warning(
            'Task %s failed to execute. This task will retry.'% task['name'])
        try: 
          self.channel.basic_publish(exchange='',
                      routing_key=self._queue_name,
                      body=json.dumps(task),
                      properties=pika.BasicProperties(
                         delivery_mode = 2, # make message persistent
                      )) 
        except pika.exceptions.AMQPConnectionError, e:
          ch.basic_reject(delivery_tag = method.delivery_tag, requeue = True)
          self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                                                    host='localhost'))
          self.channel = self.connection.channel()
        except pika.exceptions.AMQPConnectionError, e:
          logging.error("Unable to connect to RabbitMQ: " + str(e))
        except Exception, e:
          logging.error("Unknown exception--unable to connect to RabbitMQ: " + str(e))
        # TODO RabbitMQ's basic_publish and reject should be 
        # done transactionally to prevent race conditions and duplicate
        # tasks being enqueued. The API does support transactions see:
        # http://www.rabbitmq.com/amqp-0-9-1-reference.html
        else:
          ch.basic_reject(delivery_tag = method.delivery_tag, requeue = False)

 
  def MainLoop(self):
    """The main loop of the scheduler."""
    reconnect_time = 1
    while 1:
      try:
        logging.info("Connecting to RabbitMQ")
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                         host='localhost'))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=self._queue_name)
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(self._TaskCallback, queue=self._queue_name)
        logging.info("Success: connected to RabbitMQ")
        self.channel.start_consuming() 
      except pika.exceptions.AMQPConnectionError, e:
        logging.error("RabbitMQ Connection error %s"%str(e))
      except Exception, e:
        logging.error("RabbitMQ Unknown exception %s"%str(e))
      logging.info("Reconnecting in " + str(reconnect_time) + " seconds")
      time.sleep(reconnect_time) 

      if reconnect_time <= MAX_RECONNECT_TIME:
        reconnect_time *= 2
      else:
        reconnect_time = MAX_RECONNECT_TIME

class TaskQueueServiceStub(apiproxy_stub.APIProxyStub):
  """Python only task queue service stub.

  This stub executes tasks when enabled by using the dev_appserver's AddEvent
  capability. When task running is disabled this stub will store tasks for
  display on a console, where the user may manually execute the tasks.
  """

  def __init__(self,
               service_name='taskqueue',
               root_path=None,
               auto_task_running=False,
               task_retry_seconds=30,
               _all_queues_valid=False,
               default_http_server=None,
               _testing_validate_state=False,
               app_id=None,
               hash_secret="xxx"): 
    """Constructor.

    Args:
      service_name: Service name expected for all calls.
      root_path: Root path to the directory of the application which may contain
        a queue.yaml file. If None, then it's assumed no queue.yaml file is
        available.
      auto_task_running: When True, the dev_appserver should automatically
        run tasks after they are enqueued.
      task_retry_seconds: How long to wait between task executions after a
        task fails.
      _testing_validate_state: Should this stub and all of its  _Groups (and
          thus and all of its _Queues) validate their state after each
          operation? This should only be used during testing of the
          taskqueue_stub.
    """
    super(TaskQueueServiceStub, self).__init__(
        service_name, max_request_size=MAX_REQUEST_SIZE)

    self._queues = {}
    self._all_queues_valid = _all_queues_valid
    self._root_path = root_path
    self._testing_validate_state = _testing_validate_state
    self._auto_task_running = auto_task_running
    self._started = False
    self._app_id = app_id
    self._secret_hash = hash_secret
    self._task_scheduler = _BackgroundTaskScheduler(
        _TaskExecutor(default_http_server, self._secret_hash), app_id, 
        retry_seconds=task_retry_seconds)
    try:
      self.connection = pika.BlockingConnection(pika.ConnectionParameters(
        host='localhost'))
      self.channel = self.connection.channel()
      self.channel.queue_declare(queue='app_%s'%app_id, durable=False)
    except pika.exceptions.AMQPConnectionError, e:
      logging.error("RabbitMQ Connection error %s"%str(e))
    except Exception, e:
      logging.error("Unknown exception--Unable to connect to to RabbitMQ")

  def StartBackgroundExecution(self):
    """Start automatic task execution."""
    if not self._started and self._auto_task_running:
      task_scheduler_thread = threading.Thread(
          target=self._task_scheduler.MainLoop)
      task_scheduler_thread.setDaemon(True)
      task_scheduler_thread.start()
      self._started = True

  def Shutdown(self):
    """Requests the task scheduler to shutdown."""
    self._task_scheduler.Shutdown()

  def _ParseQueueYaml(self):
    """Loads the queue.yaml file and parses it.

    Returns:
      None if queue.yaml doesn't exist, otherwise a queueinfo.QueueEntry object
      populated from the queue.yaml.
    """
    if hasattr(self, 'queue_yaml_parser'):
      return self.queue_yaml_parser(self._root_path)

    if self._root_path is None:
      return None
    for queueyaml in ('queue.yaml', 'queue.yml'):
      try:
        fh = open(os.path.join(self._root_path, queueyaml), 'r')
      except IOError:
        continue
      try:
        queue_info = queueinfo.LoadSingleQueue(fh)
        return queue_info
      finally:
        fh.close()
    return None

  def _UpdateNextEventTime(self, callback_time):
    """Enqueue a task to be automatically scheduled.

    Note: If auto task running is disabled, this function is a no-op.

    Args:
      callback_time: The earliest time this task may be run, in seconds since
        the epoch.
    """
    self._task_scheduler.UpdateNextEventTime(callback_time)

  def _Dynamic_Add(self, request, response):
    """Add a single task to a queue.

    This method is a wrapper around the BulkAdd RPC request.

    Must adhere to the '_Dynamic_' naming convention for stubbing to work.
    See taskqueue_service.proto for a full description of the RPC.

    Args:
      request: The taskqueue_service_pb.TaskQueueAddRequest. See
          taskqueue_service.proto.
      response: The taskqueue_service_pb.TaskQueueAddResponse. See
          taskqueue_service.proto.
    """
    bulk_request = taskqueue_service_pb.TaskQueueBulkAddRequest()
    bulk_response = taskqueue_service_pb.TaskQueueBulkAddResponse()

    bulk_request.add_add_request().CopyFrom(request)
    self._Dynamic_BulkAdd(bulk_request, bulk_response)

    assert bulk_response.taskresult_size() == 1
    result = bulk_response.taskresult(0).result()

    if result != taskqueue_service_pb.TaskQueueServiceError.OK:
      raise apiproxy_errors.ApplicationError(result)
    elif bulk_response.taskresult(0).has_chosen_task_name():
      response.set_chosen_task_name(
          bulk_response.taskresult(0).chosen_task_name())

  def _Dynamic_BulkAdd(self, request, response):
    """Add many tasks to a queue using a single request.

    Must adhere to the '_Dynamic_' naming convention for stubbing to work.
    See taskqueue_service.proto for a full description of the RPC.

    Args:
      request: The taskqueue_service_pb.TaskQueueBulkAddRequest. See taskqueue_service.proto.
      response: The taskqueue_service_pb.TaskQueueBulkAddResponse. See
          taskqueue_service.proto.
    """
    assert request.add_request_size(), 'taskqueue should prevent empty requests'
    error_found = False
    task_results_with_chosen_names = set()
    now = datetime.datetime.utcfromtimestamp(time.time())
    for add_request in request.add_request_list():
      task_result = response.add_taskresult()
      result = _VerifyTaskQueueAddRequest(add_request, now)
      if result == taskqueue_service_pb.TaskQueueServiceError.OK:
        if not add_request.task_name():
          # Acquire a unique task name
          chosen_name = _ChooseTaskName()
          add_request.set_task_name(chosen_name)
          task_results_with_chosen_names.add(id(task_result))
        task_result.set_result(
            taskqueue_service_pb.TaskQueueServiceError.SKIPPED)
      else:
        error_found = True
        task_result.set_result(result)

    if error_found:
      return
    
    if request.add_request(0).has_transaction():
      self._TransactionalBulkAdd(request)
    else:
      self._NonTransactionalBulkAdd(request, response, now)

    for add_request, task_result in zip(request.add_request_list(),
                                        response.taskresult_list()):
      if (task_result.result() ==
          taskqueue_service_pb.TaskQueueServiceError.SKIPPED):
        task_result.set_result(taskqueue_service_pb.TaskQueueServiceError.OK)
      if id(task_result) in task_results_with_chosen_names:
        task_result.set_chosen_task_name(add_request.task_name())

  def _TransactionalBulkAdd(self, request):
    """Uses datastore.AddActions to associate tasks with a transaction.

    Args:
      request: The taskqueue_service_pb.TaskQueueBulkAddRequest containing the
        tasks to add. N.B. all tasks in the request have been validated and
        assigned unique names.
    """
    try:
      apiproxy_stub_map.MakeSyncCall(
          'datastore_v3', 'AddActions', request, api_base_pb.VoidProto())
    except apiproxy_errors.ApplicationError, e:
      raise apiproxy_errors.ApplicationError(
          e.application_error +
          taskqueue_service_pb.TaskQueueServiceError.DATASTORE_ERROR,
          e.error_detail)

  def _NonTransactionalBulkAdd(self, request, response, now):
    """Adds tasks to the appropriate _Queue instance.

    Args:
      request: The taskqueue_service_pb.TaskQueueBulkAddRequest containing the
        tasks to add. N.B. all tasks in the request have been validated and
        those with empty names have been assigned unique names.
      response: The taskqueue_service_pb.TaskQueueBulkAddResponse to populate
        with the results. N.B. the chosen_task_name field in the response will
        not be filled-in.
      now: A datetime.datetime object containing the current time in UTC.
    """
    queue_mode = request.add_request(0).mode()
    queue_name = request.add_request(0).queue_name()
    for add_request, task_result in zip(request.add_request_list(),
                                        response.taskresult_list()):
      try:
        self._enqueue_task(add_request, now)
      except apiproxy_errors.ApplicationError, e:
        task_result.set_result(e.application_error)
      else:
        task_result.set_result(taskqueue_service_pb.TaskQueueServiceError.OK)

  def _enqueue_task(self, request, now):
    """Enqueues the task into rabbitmq
    """ 
    # Make sure the task doesnt  already exist or tombstoned
    self._LocateTaskByName(request.task_name())

    now_sec = calendar.timegm(now.utctimetuple())
    task = taskqueue_service_pb.TaskQueueQueryTasksResponse_Task()
    task.set_task_name(request.task_name())
    task.set_eta_usec(request.eta_usec())
    task.set_creation_time_usec(_SecToUsec(now_sec))
    task.set_retry_count(0)
    task.set_method(request.method())

    if request.has_url():
      task.set_url(request.url())
    for keyvalue in request.header_list():
      header = task.add_header()
      header.set_key(keyvalue.key())
      header.set_value(keyvalue.value())
    if request.has_description():
      task.set_description(request.description())
    if request.has_body():
      task.set_body(request.body())
    if request.has_crontimetable():
      task.mutable_crontimetable().set_schedule(
          request.crontimetable().schedule())
      task.mutable_crontimetable().set_timezone(
          request.crontimetable().timezone())
    if request.has_retry_parameters():
      task.mutable_retry_parameters().CopyFrom(request.retry_parameters())
    if request.has_tag():
      task.set_tag(request.tag())
    # Unable to turn the pb into a string and decode it, truncated error comes up
    queue_name = 'app_%s'%self._app_id
    task_dict = QueryTasksResponseToDict(queue_name, 
                                         task, 
                                         now, 
                                         self._secret_hash)
    task_dict = json.dumps(task_dict)
    #logging.info("Enqueuing task: %s"%task_dict)
    try:
      entity = datastore.Entity(_TASKQUEUE_KIND,
                                name=str(task.task_name()), namespace='')
      entity.update({'state': TaskStates.Running, 'name':task.task_name()})
      datastore.Put(entity)
      ret = self.channel.basic_publish(exchange='',
                      routing_key=queue_name,
                      body=task_dict,
                      properties=pika.BasicProperties(
                         delivery_mode = 2, # make message persistent
                      )) 
    except pika.exceptions.AMQPConnectionError, e:
      ch.basic_reject(delivery_tag = method.delivery_tag, requeue = True)
      self.connection = pika.BlockingConnection(pika.ConnectionParameters(
                                                   host='localhost'))
      raise apiproxy_errors.ApplicationError(
                 taskqueue_service_pb.TaskQueueServiceError.TRANSIENT_ERROR)
    except Exception, e:
      logging.error("Unknown exception--Unable to connect to RabbitMQ")

  def _LocateTaskByName(self, task_name):
    """ Makes sure the task does not exist or tombstoned
    """
    key = datastore.Key.from_path(_TASKQUEUE_KIND, task_name, namespace='')
    db_task = None
    try:
      db_task = datastore.Get(key)
    except datastore_errors.EntityNotFoundError, err:
      return None
    else:
      if not db_task:
        return None
      if db_task['state'] == TaskStates.Running:
        raise apiproxy_errors.ApplicationError(
          taskqueue_service_pb.TaskQueueServiceError.TASK_ALREADY_EXISTS)
      if db_task['state'] == TaskStates.Tombstoned:
        raise apiproxy_errors.ApplicationError(
          taskqueue_service_pb.TaskQueueServiceError.TOMBSTONED_TASK)
      else: 
        logging.error("Bad state for task %s was set to %s"%(db_task['name'], db_task['state'])) 
        return None
    return None
 
  def _Dynamic_PurgeQueue(self, request, response):
    """Local purge implementation of TaskQueueService.PurgeQueue.

    Must adhere to the '_Dynamic_' naming convention for stubbing to work.
    See taskqueue_service.proto for a full description of the RPC.

    Args:
      request: A taskqueue_service_pb.TaskQueuePurgeQueueRequest.
      response: A taskqueue_service_pb.TaskQueuePurgeQueueResponse.
    """
    queue_name = "app_%s"%self._app_id
    self.channel.queue_purge(queue=queue_name) 
    #TODO purge the datastore of TQ state

