import configparser

config = configparser.ConfigParser()
config.read("imageio/config.ini")

IMAGEIO = config["imageio"]
PROXY = config["proxy"]
SSL = config["ssl"]
LOGGING = config["logging"]

