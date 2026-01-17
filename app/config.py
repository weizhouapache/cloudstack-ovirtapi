import configparser

config = configparser.ConfigParser()
config.read("config.ini")

SERVER = config["server"]
CLOUDSTACK = config["cloudstack"]
SECURITY = config["security"]
SSL = config["ssl"]

