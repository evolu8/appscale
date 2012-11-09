package com.google.appengine.tools.development;

import java.awt.Toolkit;
import java.io.File;
import java.io.PrintStream;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.TimeZone;

import com.google.appengine.tools.info.SdkInfo;
import com.google.appengine.tools.info.UpdateCheck;
import com.google.appengine.tools.util.Action;
import com.google.appengine.tools.util.Logging;
import com.google.appengine.tools.util.Option;
import com.google.appengine.tools.util.Parser;

public class DevAppServerMain {
    private static String originalTimeZone;
    private final Action ACTION = new StartAction();

    private String server = SdkInfo.getDefaultServer();

    private String address = "127.0.0.1";
    private int port = 8080;
    private boolean disableUpdateCheck;
    private String generatedDirectory = null;

    // add for AppScale
    private String db_location;
    private String login_server;
    private String cookie;
    private String appscale_version;
    private String admin_console_version;

    private final List<Option> PARSERS = Arrays.asList(new Option[] {
            new Option("h", "help", true) {
                public void apply() {
                    DevAppServerMain.printHelp(System.err);
                    System.exit(0);
                }
            }, new Option("s", "server", false) {
                public void apply() {
                    server = getValue();
                }
            }, new Option("a", "address", false) {
                public void apply() {
                    address = getValue();
                    System.setProperty("SERVER_NAME", getValue());
                }
            }, new Option("p", "port", false) {
                public void apply() {
                    port = Integer.valueOf(getValue()).intValue();
                }
            }, new Option(null, "sdk_root", false) {
                public void apply() {
                    System.setProperty("appengine.sdk.root", getValue());
                }
            }, new Option(null, "disable_update_check", true) {
                public void apply() {
                    disableUpdateCheck = true;
                }
            }, new Option(null, "datastore_path", false) {
                public void apply() {
                    db_location = getValue();
                    System.setProperty("DB_LOCATION", db_location);
                }
            }, new Option(null, "generated_dir", false) {
                public void apply() {
                    generatedDirectory = getValue();
                }
            },new Option(null, "login_server", false) {
                public void apply() {
                    login_server = getValue();
                    System.setProperty("LOGIN_SERVER", login_server);
                }
            }, new Option(null, "cookie_secret", false) {
                public void apply() {
                    cookie = getValue();
                    System.setProperty("COOKIE_SECRET", cookie);
                }
            }, new Option(null, "appscale_version", false) {
                public void apply() {
                    appscale_version = getValue();
                    System.setProperty("APP_SCALE_VERSION", appscale_version);
                }
            }, new Option(null, "admin_console_server", false) {
                public void apply() {
                    admin_console_version = getValue();
                    System.setProperty("ADMIN_CONSOLE_VERSION", admin_console_version);
                }
            }, new Option(null, "NGINX_ADDRESS", false) {
                public void apply() {
                    // admin_console_version = getValue();
                    System.setProperty("NGINX_ADDR", getValue());
                }
            }, new Option(null, "NGINX_PORT", false) {
                public void apply() {
                    // admin_console_version = getValue();
                    System.setProperty("NGINX_PORT", getValue());
                }
            }
    });

    public static void main(String[] args) throws Exception {
        recordTimeZone();
        Logging.initializeLogging();
        if (System.getProperty("os.name").equalsIgnoreCase("Mac OS X")) {
            Toolkit.getDefaultToolkit();
        }
        new DevAppServerMain(args);
    }

    private static void recordTimeZone() {
        originalTimeZone = System.getProperty("user.timezone");
    }

    public DevAppServerMain(String[] args) throws Exception {
        Parser parser = new Parser();
        Parser.ParseResult result = parser.parseArgs(this.ACTION, this.PARSERS,args);
        result.applyArgs();
    }

    public static void printHelp(PrintStream out) {
        out.println("Usage: <dev-appserver> [options] <war directory>");
        out.println("");
        out.println("Options:");
        out.println(" --help, -h                 Show this help message and exit.");
        out.println(" --server=SERVER            The server to use to determine the latest");
        out.println("  -s SERVER                   SDK version.");
        out.println(" --address=ADDRESS          The address of the interface on the local machine");
        out.println("  -a ADDRESS                  to bind to (or 0.0.0.0 for all interfaces).");
        out.println(" --port=PORT                The port number to bind to on the local machine.");
        out.println("  -p PORT");
        out.println(" --sdk_root=root            Overrides where the SDK is located.");
        out.println(" --disable_update_check     Disable the check for newer SDK versions.");
        out.println(" --generated_dir=dir        Set the directory where generated files are created.");
    }

    public static void validateWarPath(File war) {
        if (!war.exists()) {
            System.out.println("Unable to find the webapp directory " + war);
            printHelp(System.err);
            System.exit(1);
        } else if (!war.isDirectory()) {
            System.out
                    .println("dev_appserver only accepts webapp directories, not war files.");
            printHelp(System.err);
            System.exit(1);
        }
    }

    class StartAction extends Action {
        StartAction() {
            super();
        }

        @SuppressWarnings("unchecked")
        public void apply() {
            List<String> args = getArgs();
            if (args.size() != 1) {
                DevAppServerMain.printHelp(System.err);
                System.exit(1);
            }
            try {
                File appDir = new File(args.get(0)).getCanonicalFile();
                DevAppServerMain.validateWarPath(appDir);

                UpdateCheck updateCheck = new UpdateCheck(DevAppServerMain.this.server, appDir, true);
                if ((updateCheck.allowedToCheckForUpdates())
                        && (!DevAppServerMain.this.disableUpdateCheck)) {
                    updateCheck.maybePrintNagScreen(System.err);
                }
                updateCheck.checkJavaVersion(System.err);

                DevAppServer server = new DevAppServerFactory()
                        .createDevAppServer(appDir,
                                DevAppServerMain.this.address,
                                DevAppServerMain.this.port);

                Properties properties = System.getProperties();

                @SuppressWarnings("rawtypes")
                Map stringProperties = properties;
                setTimeZone(stringProperties);
                setGeneratedDirectory(stringProperties);
                server.setServiceProperties(stringProperties);

                server.start();
                try {
                    while (true) {
                        Thread.sleep(3600000L);
                    }
                } catch (InterruptedException e) {
                    System.out.println("Shutting down.");
                    System.exit(0);
                }
            } catch (Exception ex) {
                ex.printStackTrace();
                System.exit(1);
            }
        }

        private void setTimeZone(Map<String, String> serviceProperties) {
            String timeZone = serviceProperties.get("appengine.user.timezone");
            if (timeZone != null)
                TimeZone.setDefault(TimeZone.getTimeZone(timeZone));
            else {
                timeZone = DevAppServerMain.originalTimeZone;
            }
            serviceProperties.put("appengine.user.timezone.impl", timeZone);
        }

        private void setGeneratedDirectory(Map<String, String> stringProperties) {
            if (DevAppServerMain.this.generatedDirectory != null) {
                File dir = new File(DevAppServerMain.this.generatedDirectory);
                String error = null;
                if (dir.exists()) {
                    if (!dir.isDirectory())
                        error = DevAppServerMain.this.generatedDirectory
                                + " is not a directory.";
                    else if (!dir.canWrite())
                        error = DevAppServerMain.this.generatedDirectory
                                + " is not writable.";
                } else if (!dir.mkdirs()) {
                    error = "Could not make "
                            + DevAppServerMain.this.generatedDirectory;
                }
                if (error != null) {
                    System.err.println(error);
                    System.exit(1);
                }
                stringProperties.put("appengine.generated.dir",
                        DevAppServerMain.this.generatedDirectory);
            }
        }
    }
}