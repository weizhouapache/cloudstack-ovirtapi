import configparser

config = configparser.ConfigParser(
    inline_comment_prefixes=(';', '#')
)
config.read("config.ini")

SERVER = config["server"]
CLOUDSTACK = config["cloudstack"]
SECURITY = config["security"]
SSL = config["ssl"]
IMAGEIO = config["imageio"]

