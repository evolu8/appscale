#Navraj Chohan
#Creates a USERS__ and APPS__ table

#Author: Navraj Chohan
import sys, time
import os 

APPSCALE_HOME = os.environ.get("APPSCALE_HOME")
if APPSCALE_HOME:
  pass
else:
  print "APPSCALE_HOME env var not set"
  exit(1)

sys.path.append(APPSCALE_HOME + "/AppDB/hbase")
sys.path.append(APPSCALE_HOME + "/AppDB")

import Hbase
import ttypes
import string
from thrift import Thrift
from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
import py_hbase
import hbase_interface
from dbconstants import *

def create_table(tablename, columns):
  client = py_hbase.DatastoreProxy()
  return client.create_table(tablename, columns)

def create_app_tables():
  db = hbase_interface.DatastoreProxy()
  db.create_table(ASC_PROPERTY_TABLE, PROPERTY_SCHEMA)
  db.create_table(DSC_PROPERTY_TABLE, PROPERTY_SCHEMA)
  db.create_table(APP_INDEX_TABLE, APP_INDEX_SCHEMA)
  db.create_table(APP_NAMESPACE_TABLE, APP_NAMESPACE_SCHEMA)
  db.create_table(APP_ID_TABLE, APP_ID_SCHEMA)
  db.create_table(APP_ENTITY_TABLE, APP_ENTITY_SCHEMA)
  db.create_table(APP_KIND_TABLE, APP_KIND_SCHEMA)


def prime_hbase():
  print "prime hbase database"
  create_app_tables()
  create_table(USERS_TABLE, USERS_SCHEMA)
  result = create_table(APPS_TABLE, APPS_SCHEMA)
  if (USERS_TABLE in result) and (APPS_TABLE in result):
    print "CREATE TABLE SUCCESS FOR USER AND APPS:"
    print result
    return 0
  else:
    print "FAILED TO CREATE TABLE FOR USER AND APPS"
    return 1

if __name__ == "__main__":
  sys.exit(prime_hbase())

