#!/usr/bin/env python
"""
@version: 0.5.0 / 2018-12-15
@author: Sergey Dryabzhinsky
@copyright: Rusoft, 2017-2018
"""

import os
import sys
import signal
from time import sleep
import argparse

import pymysql
from pymysql.cursors import DictCursor
from packaging import version

try:
    # Python 2
    import ConfigParser as cfp
except:
    import configparser as cfp

# Wait only a hour
WAIT_TIME = 3600
BREAK_WAIT = False


class Config(object):
    """Configure me so examples work

    Use me like this:

        mysql.connector.Connect(**Config.dbinfo())
    """

    HOST = 'localhost'
    DATABASE = 'database'
    USER = 'user'
    PASSWORD = 'password'
    PORT = 3306

    CHARSET = 'utf8'
    UNICODE = True

    TIMEOUT_CON = 10

    @classmethod
    def dbinfo(cls):
        return {
            'host': cls.HOST,
            'port': cls.PORT,
            'db': cls.DATABASE,
            'user': cls.USER,
            'passwd': cls.PASSWORD,
            'charset': cls.CHARSET,
            'use_unicode': cls.UNICODE,
            'cursorclass': DictCursor,
            'connect_timeout': cls.TIMEOUT_CON
        }

class DataBase(object):

    _connection = None

    def getConnection( self, dbinfo=None ):
        if self._connection:
            try:
                if not self._connection.ping(True):
                    self._connection = None
            except:
                self._connection = None
                pass

        if not self._connection:
            config = Config.dbinfo().copy()
            if dbinfo and type(dbinfo) is dict:
                config.update(dbinfo)
            self._connection = pymysql.connect(**config)
        return self._connection

    def getCursor(self):
        return self.getConnection().cursor()


    def ping(self):
        cur = self.getCursor()
        cur.execute("SELECT 1;")
        cur.close()

    def getServerVersion(self):
        cur = self.getCursor()
        cur.execute("SELECT VERSION() as v;")
        vers = cur.fetchone()
        cur.close()
        if vers:
            vers = vers['v'].split("-")[0]
        return vers

    def lockServerReadonly(self):
        cur = self.getCursor()
        if version.parse(self.getServerVersion()) >= version.parse("5.5.0"):
            cur.execute("FLUSH ENGINE LOGS;")
        cur.execute("FLUSH LOGS;")
        cur.execute("FLUSH TABLES WITH READ LOCK;")
        cur.execute("SET GLOBAL read_only = ON;")
        cur.close()

    def unlockServerReadonly(self):
        cur = self.getCursor()
        cur.execute("SET GLOBAL read_only = OFF;")
        cur.execute("UNLOCK TABLES;")
        cur.close()


def find_cnfs(add_cnfs=[]):
    files = [ os.path.expanduser('~/.my.cnf'), '/etc/mysql/root.cnf', '/etc/mysql/debian.cnf' ]
    if len(add_cnfs) > 1:
        files.extend(add_cnfs)
    f = []
    for fn in files:
        if os.path.exists(fn) and os.access(fn, os.R_OK):
            f.append(fn)
    if not f:
        raise RuntimeError("Can't read mysql cnf files to connect to server!")
    return f

def read_cnf(f):
    cfg = cfp.RawConfigParser()
    cfg.read(f)
    return cfg


# Signal handler
def break_lock(signum, frame):
    global BREAK_WAIT
    BREAK_WAIT=True
    return

signal.signal(signal.SIGINT, break_lock)
signal.signal(signal.SIGTERM, break_lock)
if hasattr(signal, "SIGABRT"):
    signal.signal(signal.SIGABRT, break_lock)

# DB global object
db = DataBase()



parser = argparse.ArgumentParser(description='Lock all MySQL databases read-only. v0.5.0')
parser.add_argument('-t','--timeout', dest='timeout', metavar='N', type=int, default=3600,
                    help='Unlock databases after N seconds and exit. Default: 3600 (hour).')
parser.add_argument('cnf', metavar='FILE', nargs='*',
                    help='Additional .cnf-files with auth credentials. Default looks for: ~/.my.cnf, /etc/mysql/root.cnf, /etc/mysql/debian.cnf.')

args = parser.parse_args()

WAIT_TIME = args.timeout



available_cnfs = find_cnfs(args.cnf)


# Try to connect with one of CNF-file, auth, and lock server
connected = False
locked = False
for cnf in available_cnfs:

    connected = False
    locked = False

    try:
        dbCfg = read_cnf(cnf)
    except Exception as e:
        sys.stderr.write("Can't read config: %s, Error: %s\n" % (cnf, e))
        continue

    if not dbCfg.has_section("client"):
        sys.stderr.write("Config %s not has section 'client'!\n")
        continue

    try:
        dbInfo = {
            "host": dbCfg.get("client", "host"),
            "user": dbCfg.get("client", "user"),
            "password": dbCfg.get("client", "password"),
            "db": None
        }
        if dbCfg.has_option("client", "port"):
            if dbCfg.getint("client", "port"):
                dbInfo["port"] = dbCfg.getint("client", "port")
        if dbCfg.has_option("client", "socket"):
            dbInfo["unix_socket"] = dbCfg.get("client", "socket")
    except Exception as e:
        sys.stderr.write("Broken config: %s, Error: %s\n" % (cnf, e))
        continue

    try:
        # Init connection
        # May not auth!
        db.getConnection(dbInfo)
        connected = True

        # Lock all tables on server
        # May not have permission
        db.lockServerReadonly()
        locked = True

        # If all ok - break cnf cycle
        break
    except:
        # Try another cnf
        continue

if not connected:
    raise RuntimeError("Can't auth on mysql server with any cnf! Cnf files: ~/.my.cnf, /etc/mysql/root.cnf, /etc/mysql/debian.cnf, script arguments.")
if not locked:
    raise RuntimeError("Can't lock mysql server readonly! No permissions!")

# Wait break signal
while WAIT_TIME > 0:
    WAIT_TIME -= 1
    sleep(1)
    # Do some action - keep connection alive
    db.ping()
    if BREAK_WAIT:
        break

db.unlockServerReadonly()
