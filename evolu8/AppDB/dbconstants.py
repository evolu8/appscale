# Constants

import os
APPSCALE_HOME=os.environ.get("APPSCALE_HOME")
SECRET_LOCATION = "/etc/appscale/secret.key"
LOG_DIR = "%s/AppDB/logs" % APPSCALE_HOME

ERROR_DEFAULT = "DB_ERROR:"
NONEXISTANT_TRANSACTION = "0"

# DB schema

USERS_TABLE = "USERS__"
APPS_TABLE = "APPS__"
JOURNAL_TABLE = "JOURNAL__"
JOURNAL_SCHEMA = [
  "Encoded_Entity"]
ENTITY_TABLE_SCHEMA = [
  "Encoded_Entity",
  "Txn_Num" ]

USERS_SCHEMA = [
  "email",
  "pw",
  "date_creation", 
  "date_change",
  "date_last_login",
  "applications",
  "appdrop_rem_token",
  "appdrop_rem_token_exp",
  "visit_cnt",
  "cookie",
  "cookie_ip",
  "cookie_exp",
  "cksum",
  "enabled",
  "type",
  "is_cloud_admin",
  "capabilities" ]

APPS_SCHEMA = [
  "name",
  "language",
  "version",
  "owner",
  "admins_list",
  "host",
  "port",
  "creation_date",
  "last_time_updated_date",
  "yaml_file",
  "cksum",
  "num_entries",
  "tar_ball",
  "enabled",
  "classes",
  "indexes" ]

APPENGINE_SCHEMA= ["""
CREATE TABLE IF NOT EXISTS Apps (
  app_id VARCHAR(255) NOT NULL PRIMARY KEY,
  indexes VARCHAR(255)
) ENGINE=ndbcluster;
""","""
CREATE TABLE IF NOT EXISTS Namespaces (
  app_id VARCHAR(255) NOT NULL,
  name_space VARCHAR(255) NOT NULL,
  PRIMARY KEY (app_id, name_space)
) ENGINE=ndbcluster;
""","""
CREATE TABLE IF NOT EXISTS IdSeq (
  prefix VARCHAR(255) NOT NULL PRIMARY KEY,
  next_id INT(100) NOT NULL
) ENGINE=ndbcluster;
"""]

