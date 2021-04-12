import uvicorn
import numpy as np
import os
import mlflow
import json
import pandas as pd
import aiohttp
import logging

from mlflow.tracking import MlflowClient
from mlflow.exceptions import  MlflowException
from typing import Optional, List, Dict

from fastapi import FastAPI, Response, Request, UploadFile
from pydantic import BaseModel, HttpUrl

logging.basicConfig(format='%(asctime)s -  %(levelname)s - %(message)s',
                    datefmt='%d-%b-%y %H:%M:%S')
logging.getLogger().setLevel(logging.INFO)


agent_name = 'Planner'
# consider put this into startup fastapi function
client = MlflowClient()

experiment = client.get_experiment_by_name(agent_name)

if experiment:
    experiment_id = experiment.experiment_id
    logging.info(f"[Planner]  '{agent_name}' experiment loaded.")
else:
    experiment_id = client.create_experiment(agent_name)
    logging.info(f"[Planner]  '{agent_name}' experiment does not exist. Creating a new one.")


app = FastAPI(title='Planner Agent API',
              description='Actions and Beliefs for the Planner Agent',
              )

@app.on_event("startup")
async def startup_event():
    app.aiohttp_session = aiohttp.ClientSession()

@app.on_event("shutdown")
async def shutdown_event():
    await app.aiohttp_session.close()

class Message(object):
    """
        Abstract Message class.

    """
    def __init__(self,
                 content: dict,
                 performative: str,
                 receiver: str):

        self.content = content
        self.performative = performative
        self.receiver = receiver


@app.post("/planner/plans",
          tags=['Actions'],
          summary="Call planner to perform plans")
async def execute_planner(conclusions: dict):
    """
    Call improver to analyze the checker's feedback.
    This agent contains some user-defined rules to take decisions

    - **performative**: Performative action (INFORM, REQUEST, CFP)
    - **content**: Client requests.
    """

    # Perform the action
    conclusions = conclusions['conclusions']

    new_model_name = conclusions['new_model_name']
    
    
#     try:
#         client.create_registered_model(name=new_model)
        
#     except:
#         client.delete_registered_model(name=new_model)
#         client.create_registered_model(name=new_model)


    client.transition_model_version_stage(
        name=conclusions['current_model_name'],
        version=conclusions['current_model_version'],
        stage="Archived"
    )
    client.transition_model_version_stage(
        name=new_model_name,
        version=1,
        stage="Staging"
    )  

    response = {'Plan': {
                    "action": conclusions['order'],
                    "current_model_name": conclusions['current_model_name'],
                    "new_model_name": new_model_name,
                    "result": f"Current model stage = Staging. New model stage = Production",
                }
              }


    improver_filename = 'plan.json'
    with open(improver_filename, 'w') as fout:
        json.dump(response, fout)

    with mlflow.start_run(experiment_id=experiment_id,
                          run_name=agent_name) as mlrun:
        mlflow.log_artifact(improver_filename, 'Plan')

    return  response

@app.get("/planner/plans/last",
         tags=['Beliefs'],
         summary='Get last Planner plans')
async def get_last_conclusions():
    runs_info = client.list_run_infos(experiment_id,
                                      order_by=["attribute.start_time DESC"])
    if runs_info:
        last_run_id = runs_info[0].run_id
        plan_artifact_path = os.path.join('Plan', 'plan.json')

        try:
            client.download_artifacts(last_run_id,
                                      plan_artifact_path,
                                      '/tmp/')
        except:
            response = {"plan": 'No plan found yet'}
            return response

        plan_local_path = os.path.join('/tmp', plan_artifact_path)
        with open(plan_local_path) as fread:
            plan = json.load(fread)

        response = {"plan": plan}
    else:
        response = {"plan": 'No experiments yet'}

    return response
