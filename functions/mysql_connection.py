import mysql.connector,os,sys
from discord.ext import commands

# class MySQL():
#   def __init__(self):
#     True

def mydb_connect():
  # https://www.mysqltutorial.org/python-connecting-mysql-databases/
  if sys.argv[1] == "--prod" or sys.argv[1] == "--production":
    DATABASE = os.getenv("DATABASE")
  else:
    DATABASE = os.getenv("DATABASETEST")
  mydb = mysql.connector.connect(
    host=os.getenv("DBHOST"),
    user=os.getenv("DBUSER"),
    password=os.getenv("DBPASS"),
    database=DATABASE
  )

  return mydb

def query(mydb,query:str):
  mydb = mydb_connect()
  mycursor = mydb.cursor()
  mycursor.execute(query)
  if "select" in query.lower():
    result = mycursor.fetchone()[0]
  mydb.commit()
  mydb.close()
  if "select" in query.lower():
    return result

def prefix(bot,ctx):
  try:
    if str(ctx.channel.type) == "private":
      return commands.when_mentioned_or("!")(bot,ctx)
    mydb = mydb_connect()
    mycursor = mydb.cursor()
    mycursor.execute(f"SELECT prefix FROM servers WHERE id='{ctx.guild.id}'")

    result = mycursor.fetchall()

    return commands.when_mentioned_or(result[0][0])(bot,ctx)
    # return commands.when_mentioned_or("!")(bot,ctx)
    # return "!"
  except:
    return "!"