import configparser

config = configparser.ConfigParser(
    inline_comment_prefixes=(';', '#')
)
config.read("imageio/config.ini")

IMAGEIO = config["imageio"]
PROXY = config["proxy"]
SSL = config["ssl"]
LOGGING = config["logging"]

