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

import logging
import helpers
from helpers import Kendra, CustomOutputParser, CustomPromptTemplate
import config
import boto3, langchain, json, re
from typing import List, Union
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
from langchain.chat_models import ChatOpenAI
# from langchain.llms import OpenAI

logger = logging.getLogger()
logger.setLevel(logging.INFO)

kendra_index_id = config.config.KENDRA_INDEX
region_name = config.config.KENDRA_REGION
kendra_docstore = Kendra(kendra_index_id = kendra_index_id,region_name=region_name)
search_description = "useful for when you need to answer questions using a document store"
tools = [
    Tool(
        name="Search",
        func=kendra_docstore.search,
        description=search_description
    )
]

# bedrock_client = boto3.client(service_name='bedrock',
#                               region_name='us-east-1')

# llm = Bedrock(
#     client=bedrock_client,
#     model_id="amazon.titan-tg1-large",
#     model_kwargs={
#             "max_tokens_to_sample":512,
            
#         },
# )

llm = ChatOpenAI(
    temperature = 0.0,
    model_name="gpt-3.5-turbo",
    openai_api_key = "Your OpenAI API Key Here")

# Set up the base template
template = config.config.template


def get_session_attributes(intent_request):
    sessionState = intent_request['sessionState']
    if 'sessionAttributes' in sessionState:
        return sessionState['sessionAttributes']
    return {}

def lambda_handler(event, context):
    logger.info('<help_desk_bot>> Lex event info = ' + json.dumps(event))

    session_attributes = get_session_attributes(event)

    logger.debug('<<help_desk_bot> lambda_handler: session_attributes = ' + json.dumps(session_attributes))
    
    currentIntent = event['sessionState']['intent']['name']
    
    
    if currentIntent is None:
        response_string = 'Sorry, I didn\'t understand.'
        return helpers.close(session_attributes,currentIntent, 'Fulfilled', {'contentType': 'PlainText','content': response_string})
    intentName = currentIntent
    if intentName is None:
        response_string = 'Sorry, I didn\'t understand.'
        return helpers.close(session_attributes,intentName, 'Fulfilled', {'contentType': 'PlainText','content': response_string})

    # see HANDLERS dict at bottom
    if HANDLERS.get(intentName, False):
        return HANDLERS[intentName]['handler'](event, session_attributes)   # dispatch to the event handler
    else:
        response_string = "The intent " + intentName + " is not yet supported."
        return helpers.close(session_attributes,intentName, 'Fulfilled', {'contentType': 'PlainText','content': response_string})
        
        
        
def query_agent(question):
    
    prompt = CustomPromptTemplate(
        template=template,
        tools=tools,
        # This omits the `agent_scratchpad`, `tools`, and `tool_names` variables because those are generated dynamically
        # This includes the `intermediate_steps` variable because that is needed
        input_variables=["input","intermediate_steps"]
    )
    output_parser = CustomOutputParser()
    llm_chain = LLMChain(llm=llm, prompt=prompt)
    tool_names = [tool.name for tool in tools]
    agent = LLMSingleActionAgent(
        llm_chain=llm_chain, 
        output_parser=output_parser,
        stop = ["---"],
        # stop=["\nObservation:", "\nNew", "\nExample", "\nHuman", "---------------"], 
        allowed_tools=tool_names
    )

    memory = ConversationBufferWindowMemory(k=2, memory_key="chat_history", return_messages=True)

    agent_executor = AgentExecutor.from_agent_and_tools(agent=agent, tools=tools, memory = memory)

    try:
        response = agent_executor.run(question)
    except ValueError as e:
        response = str(e)
        print(response)
        if not response.startswith("Could not parse LLM output: `"):
            raise e
        response = response.removeprefix("Could not parse LLM output: `").removesuffix("`")
    return response        

def all_handler(intent_request, session_attributes):
    
    query_string = ""
    #if intent_request.get('inputTranscript', None) is not None:
    query_string += intent_request['transcriptions'][0]['transcription']

    logger.debug('<<help_desk_bot>> fallback_intent_handler(): calling get_kendra_answer(query="%s")', query_string)
        
    agent_response = query_agent(query_string)
    #kendra_response = helpers.simple_orchestrator(query_string)
    if agent_response is None:
        response = "Sorry, I was not able to understand your question."
        return helpers.close(intent_request,session_attributes,'Fulfilled', {'contentType': 'PlainText','content': response})
    else:
        logger.debug('<<help_desk_bot>> "fallback_intent_handler(): kendra_response = %s', agent_response)
        return helpers.close(intent_request,session_attributes, 'Fulfilled', {'contentType': 'PlainText','content': agent_response})
    

# list of intent handler functions for the dispatch proccess
HANDLERS = {
    'greeting_intent':              {'handler': all_handler},
    'FallbackIntent':           {'handler': all_handler}
}



    