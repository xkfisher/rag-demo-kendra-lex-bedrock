#
# Copyright 2020 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

import os
import config
import boto3, json, re, botocore, logging, time, pprint
from io import BytesIO
from langchain.docstore.document import Document
from langchain.agents import (
    load_tools,initialize_agent,Tool, AgentExecutor, LLMSingleActionAgent, AgentOutputParser ,
    ZeroShotAgent, Tool, AgentExecutor ,ReActChain)
from langchain.agents.react.base import DocstoreExplorer
from langchain.prompts import StringPromptTemplate
from langchain import LLMChain
from langchain.schema import AgentAction, AgentFinish, OutputParserException
from langchain.docstore.base import Docstore
from langchain.llms import Bedrock
from langchain.memory import ConversationBufferWindowMemory

from typing import List, Union


logger = logging.getLogger()
logger.setLevel(logging.INFO)

# kendra_client = boto3.client('kendra')
# bedrock_client = boto3.client(service_name='bedrock',
#                               region_name='us-east-1')


class Kendra(Docstore):
    """Wrapper around Kendra API."""

    def __init__(self,kendra_index_id :str, region_name:str) -> None:
        """Check that boto3 package is installed."""
        
        self.used = False
        self.URL = ""
        
        try:
            import boto3
            self.kendra_client = boto3.client("kendra",region_name=region_name)
            self.s3_client = boto3.client("s3")
            self.kendra_index_id = kendra_index_id
            
        except ImportError:
            raise ValueError(
                "Could not import boto3 python package. "
                "Please it install it with `pip install boto3`."
            )

    def parseResponse(self,response):
        for each_loop in response['ResultItems'][0]['DocumentAttributes']:
            if (each_loop['Key']=='_excerpt_page_number'):
                pagenumber = each_loop['Value']['LongValue'] -1   
        return pagenumber
    
    def parseBucketandKey(self,SourceURI):
        return (SourceURI.split('/', 3)[2],SourceURI.split('/', 3)[3])


    #def search(self, query : str ) -> str, Document]:
    def search(self, query : str ) -> str:
        """Try to search for a document in Kendra Index""
        
        """
        try:
            page_size = 4
            page_number = 1

            result =  self.kendra_client.retrieve(
                    IndexId = self.kendra_index_id,
                    QueryText = query,
                    PageSize = page_size,
                    PageNumber = page_number)
        except:
            return "RELAVENT PASSAGES NOT FOUND"

        # Concatinating the results from Kendra Retreive API 
        # https://docs.aws.amazon.com/kendra/latest/dg/searching-retrieve.html
        context =""
        for retrieve_result in result["ResultItems"]:
            context =context +'['
            context = context + "Title: " + str(retrieve_result["DocumentTitle"] + ", URI: " + str(retrieve_result["DocumentURI"]) +", Passage content: " + str(retrieve_result["Content"]))
            context =context + '] '
        return context
        
class CustomOutputParser(AgentOutputParser):
    ai_prefix: str = "AI"
    def get_format_instructions(self) -> str:
        return FORMAT_INSTRUCTIONS

    
    def parse(self, text: str) -> Union[AgentAction, AgentFinish]:
#         print("PARSED: ", text)
        if f"{self.ai_prefix}:" in text:
            return AgentFinish(
                {"output": text.split(f"{self.ai_prefix}:")[-1].strip()}, text
            )
        regex = r"Action: (.*?)[\n]*Action Input: ((.|\n)*)"
        match = re.search(regex, text)
        if not match:
            
            print("text :",text)
            raise OutputParserException(f"Could not parse LLM output: `{text}`")
        action = match.group(1)
        action_input = match.group(2)
        return AgentAction(action.strip(), action_input.strip(" ").strip('"'), text)
        
        
# Set up a prompt template
class CustomPromptTemplate(StringPromptTemplate):
    # The template to use
    template: str
    # # The list of tools available
    tools: List[Tool]
    
    def format(self, **kwargs) -> str:
        # Get the intermediate steps (AgentAction, Observation tuples)
        # Format them in a particular way
        intermediate_steps = kwargs.pop("intermediate_steps")
        thoughts = ""
        for action, observation in intermediate_steps:
            thoughts += action.log
            thoughts += f"\nObservation: {observation}\nThought: "
        # Set the agent_scratchpad variable to that value
        kwargs["agent_scratchpad"] = thoughts
        # Create a tools variable from the list of tools provided
        kwargs["tools"] = "\n".join([f"{tool.name}: {tool.description}" for tool in self.tools])
        # Create a list of tool names for the tools provided
        kwargs["tool_names"] = ", ".join([tool.name for tool in self.tools])
        return self.template.format(**kwargs)



def close(intent_request,session_attributes,fulfillment_state, message):

    response = {
                    'sessionState': {
                        'sessionAttributes': session_attributes,
                		'dialogAction': {
                            'type': 'Close'
                        },
                        'intent': intent_request['sessionState']['intent']
                        },
                    'messages': [message],
                    'sessionId': intent_request['sessionId']
                }
    response['sessionState']['intent']['state'] = fulfillment_state
    
        
    logger.info('<<help_desk_bot>> "Lambda fulfillment function response = \n' + pprint.pformat(response, indent=4)) 

    return response


    
    
    
    
