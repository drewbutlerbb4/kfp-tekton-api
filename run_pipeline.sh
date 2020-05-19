#!/bin/bash

kubectl apply -f ./pipelines/condition.yaml > /dev/null
tkn pipeline start flip-coin-example-pipeline | grep 'Pipelinerun started'