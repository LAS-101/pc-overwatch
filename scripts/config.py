import os 
from dotenv import find_dotenv,load_dotenv

dotenv_path=find_dotenv()
load_dotenv(dotenv_path)
token_key=os.getenv("token_key")
chat_id=os.getenv("chat_id")
PC_NAME=os.getenv("PC_NAME")