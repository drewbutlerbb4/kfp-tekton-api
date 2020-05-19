from flask import Flask, request
from flask_cors import CORS, cross_origin
#from flask_restplus import Api, abort, Resource, reqparse
import json
import subprocess
import yaml
import pprint

"""
Status Interface Format
export interface Status{
  workflowNodes: {
    id: string, 
    startedAt: string, 
    finishedAt: string, 
    message: string, 
    phase: NodePhase
  }[]
}
"""

# *******************************************
# **********  File Utils  *******************
# *******************************************

def _write_context(file_path, data):
    with open(file_path, 'w') as outfile:
        json.dump(data, outfile)

def _load_context(file_path):
    with open(file_path) as f:
        cur_context = json.load(f)
        return cur_context

def write_context(data):
    return _write_context(CONTEXT_PATH, data)

def load_context():
    return _load_context(CONTEXT_PATH)

def collect_logs(logs):
    logs_yaml = yaml.safe_load(logs)
    pod_names = list(logs_yaml['status']['taskRuns'].keys())
    added_conditions = []
    all_node_status = []
    is_run_failed = False

    for pod_name in pod_names:

        status = {
            "id": logs_yaml['status']['taskRuns'][pod_name]["pipelineTaskName"]
        }
        status_report = logs_yaml['status']['taskRuns'][pod_name].get('status')
        # Check if status has been initialized yet
        if not status_report == None:
            startedAt = status_report.get('startTime')

            # Check if status has been populated with information
            if not startedAt == None:
                status['startedAt'] = startedAt
                status['finishedAt'] = status_report.get('completionTime')
                # TODO: Update so that message and phase can be collected from Tasks with multiple steps

                terminated_info = status_report['steps'][0].get('terminated')
                if terminated_info != None:
                    status['message'] = terminated_info.get('message', '')
                    status['phase'] = 'Succeeded' if terminated_info.get('exitCode') == 0 else 'Error'
                    is_run_failed = terminated_info.get('exitCode') != 0 | is_run_failed
                    all_node_status.append(status)
                else:
                    status['message'] = ''
                    status['phase'] = 'Pending'

        conditions = logs_yaml['status']['taskRuns'][pod_name].get('conditionChecks', [])
        for condition in conditions:
            cond_name = conditions[condition]['conditionName'][:-2]
            if  not cond_name in added_conditions:
                # TODO: Make sure that messages and phases can be collected from Tasks with multiple conditions

                # Make sure that the condition was initialized
                if conditions[condition].get('status') != None:
                    condition_report = conditions[condition]['status']['check'].get('terminated')
                    if condition_report != None:
                        status = {
                            "id": cond_name,
                            "startedAt": condition_report['startedAt'],
                            "finishedAt": condition_report['finishedAt'],
                            "message": condition_report['reason'],
                            "phase": 'Succeeded' if condition_report['exitCode'] == 0 else 'Error'
                        }
                        added_conditions.append(cond_name)
                        all_node_status.append(status)

    #pprint.PrettyPrinter(indent=2).pprint(all_node_status)

    to_return = {
        "workflowNodes": all_node_status,
        "runName": logs_yaml['metadata']['name'] if logs_yaml['metadata'] else "Pending...",
        "runPhase": 'Error' if is_run_failed else 'Succeeded',
    }
    if logs_yaml['status'].get('completionTime') != None:
        to_return['completionTime'] = logs_yaml['status'].get('completionTime')
    else:
        to_return['completionTime'] = None
        to_return['runPhase'] = 'Pending'

    return to_return

# *******************************************
# **********  Flask Server  *****************
# *******************************************

flask_app = Flask(__name__)
flask_app.config['CORS_HEADERS'] = 'Content-Type'
#app = Api(app = flask_app)
cors = CORS(flask_app, resources={r"/*": {"origins": "*"}})

#name_space = app.namespace('main', description='Main APIs')

NEW_CONTEXT_PATH = './new_context.json'
CONTEXT_PATH = './current_context.json'

new_context_obj = _load_context(NEW_CONTEXT_PATH)
#_write_context(CONTEXT_PATH, new_context_obj)

@flask_app.route("/connect")
@cross_origin()
def connect():
    cur_context = load_context()
    is_connected = cur_context['is_connected']
    if not is_connected:
        cur_context['is_connected'] = True
        write_context(cur_context)
        return {"status": "Connection completed"}
    else:
        return {"status": "Connection failed"}
            

@flask_app.route("/disconnect")
@cross_origin()
def disconnect():
    cur_context = load_context()
    is_connected = cur_context['is_connected']
    if is_connected:
        cur_context['is_connected'] = False
        write_context(cur_context)
        return {"status": "Disconnected"}
    else:
        return {"status": "Can't disconnect"}

@flask_app.route("/start/<string:pipeline_name>")
@cross_origin()
def start(pipeline_name):
    url_params = list(request.args.keys())
    cur_post = request.json

    cur_context = load_context()
    is_connected = cur_context['is_connected']
    if is_connected:
        process = subprocess.run(['./run_pipeline.sh'], capture_output=True)
        std_out = process.stdout.decode('utf-8')

        cur_pipeline = std_out[21:-1]
        cur_context['cur_pipeline'] = cur_pipeline
        
        cur_context['runs_list'].append(cur_pipeline)
        write_context(cur_context)

        return {"status": std_out}
    else:
        return {"status": "No connection established"}
        
@flask_app.route("/logs")
@cross_origin()
def log():
    cur_context = load_context()
    is_connected = cur_context['is_connected']
    cur_pipeline = cur_context['cur_pipeline']
    if is_connected:
        if cur_pipeline:
            process = subprocess.run(['./get_pipelinerun_logs.sh', cur_pipeline], capture_output=True)
            std_out = process.stdout.decode('utf-8')
            status = collect_logs(std_out)

            return {"status": status}
        else:
            return {"status": "No pipeline running"}
    else:
        return {"status": "No connection established"}

@flask_app.route("/pipeline_list")
@cross_origin()
def pipeline_list():
    cur_context = load_context()
    is_connected = cur_context['is_connected']
    pipeline_list = cur_context['pipeline_list']
    if is_connected:
        return {"status": pipeline_list}
    else:
        return {"status": "No connection established"}

@flask_app.route("/run_list")
@cross_origin()
def run_list():
    cur_context = load_context()
    is_connected = cur_context['is_connected']
    runs_list = cur_context['runs_list']
    if is_connected:
        return {"status": runs_list}
    else:
        return {"status": "No connection established"}


@flask_app.route("/status_change")
@cross_origin()
def status_change():
    key = request.args['key']
    value = request.args['value']

    cur_context = load_context()
    is_connected = cur_context['is_connected']
    if is_connected:
        if cur_context['state'][key]:
            cur_context['state'][key] = value
            return {"status": {'key': key, 'value': value}}
    else:
        return {"status": "No connection established"}