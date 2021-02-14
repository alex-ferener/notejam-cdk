#!/usr/bin/env python3

import os
from aws_cdk import core
from notejam.notejam_stack import NotejamStack

app = core.App()

account = os.environ.get("AWS_ACCOUNT_ID")
region = os.environ.get("AWS_REGION")
env = os.environ.get("CDK_ENV_NAME")

stack = NotejamStack(
    app, f"notejam-{env}",
    env=core.Environment(account=account, region=region))

core.Tags.of(stack).add("Environment", env)
core.Tags.of(stack).add("CDK-App", "Notejam")

app.synth()
