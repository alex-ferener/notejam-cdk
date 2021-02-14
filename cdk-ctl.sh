#!/usr/bin/env bash
set -e

if [[ $# -lt 2 ]]; then
    echo 1>&2 "Provide command and environment as first args"
    exit 1
fi

export CDK_CMD=$1
export CDK_ENV_NAME=$2
shift;
shift;

set -a
source cdk.${CDK_ENV_NAME}.env
set +a

npx cdk ${CDK_CMD} "$@"
exit $?
