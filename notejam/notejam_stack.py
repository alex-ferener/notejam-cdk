import os

from aws_cdk.aws_cloudfront import Distribution, BehaviorOptions, ViewerProtocolPolicy, AllowedMethods, CachePolicy, \
    PriceClass, OriginProtocolPolicy, OriginRequestPolicy
from aws_cdk.aws_cloudfront_origins import LoadBalancerV2Origin
from aws_cdk.aws_codebuild import BuildSpec, BuildEnvironment, PipelineProject, LinuxBuildImage
from aws_cdk.aws_codepipeline import Artifact, Pipeline
from aws_cdk.aws_codepipeline_actions import GitHubSourceAction, GitHubTrigger, CodeBuildAction, EcsDeployAction
from aws_cdk.aws_ec2 import Vpc, SubnetConfiguration, SubnetType, InstanceClass, InstanceSize, Port, \
    SecurityGroup, InstanceType, SubnetSelection, Peer
from aws_cdk.aws_ecs import Cluster, ContainerImage, TaskDefinition, NetworkMode, Compatibility, PortMapping, Secret, \
    FargateService, LogDrivers
from aws_cdk.aws_ecr import Repository
from aws_cdk.aws_elasticache import CfnSubnetGroup, CfnReplicationGroup
from aws_cdk.aws_elasticloadbalancingv2 import ApplicationLoadBalancer, ApplicationProtocol, HealthCheck
from aws_cdk.aws_iam import ManagedPolicy
from aws_cdk.aws_rds import DatabaseCluster, AuroraMysqlEngineVersion, Credentials, DatabaseClusterEngine, InstanceProps
from aws_cdk.core import Stack, Construct, SecretValue, RemovalPolicy, Duration, CfnOutput
from aws_cdk.pipelines import CdkPipeline, SimpleSynthAction


class NotejamStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ==========================================================================================
        # Inputs

        env = os.environ.get('CDK_ENV_NAME')
        github_owner = os.environ.get("GITHUB_OWNER")
        github_repo_cdk = os.environ.get("GITHUB_REPO_CDK")
        github_repo_app = os.environ.get("GITHUB_REPO_APP")
        vpc_cidr = os.environ.get('VPC_CIDR')
        min_capacity = os.environ.get('MIN_CAPACITY')
        desired_capacity = os.environ.get('DESIRED_CAPACITY')
        max_capacity = os.environ.get('MAX_CAPACITY')

        # ==========================================================================================
        # CDK CI/CD Pipeline

        source_artifact = Artifact()
        cloud_assembly_artifact = Artifact()

        CdkPipeline(
            self, "Pipeline",
            cloud_assembly_artifact=cloud_assembly_artifact,
            source_action=GitHubSourceAction(
                action_name="GitHub",
                output=source_artifact,
                oauth_token=SecretValue.secrets_manager("notejam", json_field="gitHubToken"),
                trigger=GitHubTrigger.WEBHOOK,
                owner=github_owner,
                repo=github_repo_cdk,
                # TODO: Use different branches for different environments
                branch="main" if env == "prod" else "main"),
            synth_action=SimpleSynthAction.standard_npm_synth(
                source_artifact=source_artifact,
                cloud_assembly_artifact=cloud_assembly_artifact,
                install_command="npm install -g aws-cdk",
                build_command="python -m pip install -r requirements.txt",
                synth_command=f"./cdk-ctl.sh synth {env}"
            )
        )

        # ==========================================================================================
        # VPC

        vpc = Vpc(
            self, "VPC",
            cidr=vpc_cidr,
            max_azs=3,
            subnet_configuration=[
                SubnetConfiguration(
                    cidr_mask=24,
                    name="Application",
                    subnet_type=SubnetType.PRIVATE
                ),
                SubnetConfiguration(
                    subnet_type=SubnetType.PUBLIC,
                    name="Public",
                    cidr_mask=28
                ), SubnetConfiguration(
                    cidr_mask=28,
                    name="Persistence",
                    subnet_type=SubnetType.PRIVATE,
                )
            ],
            nat_gateways=3
        )

        # ==========================================================================================
        # Security Groups

        rds_security_group = SecurityGroup(
            self, "RDS",
            vpc=vpc,
            description="RDS Security Group",
            allow_all_outbound=False
        )

        redis_security_group = SecurityGroup(
            self, "RedisSG",
            vpc=vpc,
            description="Redis Security Group",
            allow_all_outbound=False
        )

        fargate_security_group = SecurityGroup(
            self, "Fargate",
            vpc=vpc,
            description="Fargate Security Group",
            allow_all_outbound=False
        )

        code_build_security_group = SecurityGroup(
            self, "CodeBuild",
            vpc=vpc,
            description="CodeBuild Security Group",
            allow_all_outbound=False
        )

        rds_security_group.connections.allow_from(fargate_security_group, Port.tcp(3306), "Fargate")
        rds_security_group.connections.allow_from(code_build_security_group, Port.tcp(3306), "CodeBuild")
        redis_security_group.connections.allow_from(fargate_security_group, Port.tcp(6379), "Fargate")

        fargate_security_group.connections.allow_to(Peer.any_ipv4(), Port.tcp(443), "ECR")
        code_build_security_group.connections.allow_to(Peer.any_ipv4(), Port.tcp(80))
        code_build_security_group.connections.allow_to(Peer.any_ipv4(), Port.tcp(443))

        # ==========================================================================================
        # Aurora Cluster

        aurora = DatabaseCluster(
            self, "Database",
            engine=DatabaseClusterEngine.aurora_mysql(version=AuroraMysqlEngineVersion.VER_2_09_1),
            instance_props=InstanceProps(
                instance_type=InstanceType.of(InstanceClass.BURSTABLE3, InstanceSize.SMALL),
                enable_performance_insights=False,
                publicly_accessible=False,
                security_groups=[rds_security_group],
                vpc_subnets=SubnetSelection(subnet_group_name="Persistence"),
                vpc=vpc
            ),
            credentials=Credentials.from_generated_secret("admin"),
            default_database_name="notejam",
            instances=2
        )

        # ==========================================================================================
        # ElasiCache - Redis

        redis_subnet_group = CfnSubnetGroup(
            self, "RedisSubnetGroup",
            subnet_ids=vpc.select_subnets(subnet_group_name="Persistence").subnet_ids,
            description="Redis"
        )

        redis = CfnReplicationGroup(
            self, "RedisRG",
            replication_group_description="Notejam",
            automatic_failover_enabled=True,
            auto_minor_version_upgrade=False,
            cache_node_type="cache.t3.micro",
            cache_parameter_group_name="default.redis6.x",
            cache_subnet_group_name=redis_subnet_group.ref,
            engine="redis",
            engine_version="6.x",
            multi_az_enabled=True,
            num_cache_clusters=2,
            security_group_ids=[redis_security_group.security_group_id],
        )

        # ==========================================================================================
        # Application Load Balancer

        lb = ApplicationLoadBalancer(self, "LB", vpc=vpc, internet_facing=True)
        listener = lb.add_listener("Listener", port=80)

        # ==========================================================================================
        # CloudFront

        origin = LoadBalancerV2Origin(lb, protocol_policy=OriginProtocolPolicy.HTTP_ONLY)

        cf = Distribution(
            self, "myDist",
            price_class=PriceClass.PRICE_CLASS_100,

            default_behavior=BehaviorOptions(
                origin=origin,
                allowed_methods=AllowedMethods.ALLOW_ALL,
                viewer_protocol_policy=ViewerProtocolPolicy.ALLOW_ALL,
                cache_policy=CachePolicy.CACHING_DISABLED,
                origin_request_policy=OriginRequestPolicy.ALL_VIEWER
            ),
            additional_behaviors={
                "*.css": BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=ViewerProtocolPolicy.ALLOW_ALL,
                )
            }
        )

        CfnOutput(
            self, "CloudFrontDomainName",
            value=cf.domain_name,
            description="CloudFront Domain Name",
            export_name=f"{self.stack_name}-cloud-front-domain-name"
        )

        # ==========================================================================================
        # ECR

        ecr_repo = Repository(self, "EcrRepo", removal_policy=RemovalPolicy.RETAIN)
        ecr_repo.add_lifecycle_rule(tag_prefix_list=[env], max_image_count=10)

        # ==========================================================================================
        # ECS

        cluster = Cluster(self, "Cluster", vpc=vpc)

        # ==========================================================================================
        # ECS - Task Definition

        task_definition = TaskDefinition(
            self, "TaskDef",
            memory_mib="2048",
            cpu="1024",
            network_mode=NetworkMode.AWS_VPC,
            compatibility=Compatibility.EC2_AND_FARGATE
        )

        container = task_definition.add_container(
            "notejam",
            image=ContainerImage.from_ecr_repository(ecr_repo, "latest"),
            memory_reservation_mib=256,
            logging=LogDrivers.aws_logs(stream_prefix="Notejam"),
            environment={
                "NODE_ENV": env,
                "REDIS_HOST": redis.get_att(attribute_name='PrimaryEndPoint.Address').to_string()
            },
            secrets={
                "DB_HOST": Secret.from_secrets_manager(aurora.secret, "host"),
                "DB_NAME": Secret.from_secrets_manager(aurora.secret, "dbname"),
                "DB_USERNAME": Secret.from_secrets_manager(aurora.secret, "username"),
                "DB_PASSWORD": Secret.from_secrets_manager(aurora.secret, "password"),
            }
        )

        container.add_port_mappings(PortMapping(container_port=3000))

        # ==========================================================================================
        # ECS - Service

        service = FargateService(
            self, "Service",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=int(desired_capacity),
            health_check_grace_period=Duration.seconds(3),
            vpc_subnets=SubnetSelection(subnet_group_name="Application"),
            security_group=fargate_security_group,
            min_healthy_percent=100,
            max_healthy_percent=200
        )

        listener.add_targets(
            "Fargate",
            port=3000,
            protocol=ApplicationProtocol.HTTP,
            health_check=HealthCheck(path="/signin", healthy_threshold_count=2),
            deregistration_delay=Duration.seconds(10),
            targets=[service]
        )

        # ==========================================================================================
        # ECS - Application Auto Scaling

        scaling = service.auto_scale_task_count(min_capacity=int(min_capacity), max_capacity=int(max_capacity))
        scaling.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=50)

        # ==========================================================================================
        # CI/CD Pipeline for Notejam App

        pipeline = Pipeline(
            self, "CodePipeline",
        )

        # ==========================================================================================
        # Source Stage - CodePipeline

        source_output = Artifact()
        source_action = GitHubSourceAction(
            oauth_token=SecretValue.secrets_manager("notejam", json_field="gitHubToken"),
            output=source_output,
            owner=github_owner,
            repo=github_repo_app,
            # TODO: Use different branch names for different environments
            branch="main" if env == "prod" else "main",
            trigger=GitHubTrigger.WEBHOOK,
            action_name="GitHub-Source",
        )

        pipeline.add_stage(
            stage_name="Source",
            actions=[source_action]
        )

        # ==========================================================================================
        # Build Stage - CodePipeline

        build_commands = [
            f"export DOCKER_TAG={env}-$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c -8)",
            f"export DOCKER_IMG={ecr_repo.repository_uri}:$DOCKER_TAG",
            f"export DOCKER_LATEST={ecr_repo.repository_uri}:latest",
            f"aws ecr get-login-password --region {self.region} | docker login --username AWS --password-stdin {ecr_repo.repository_uri}",
            "docker build -t $DOCKER_IMG -t $DOCKER_LATEST -f ./docker/ecs/Dockerfile . ",
            "docker push $DOCKER_IMG",
            "docker push $DOCKER_LATEST",
            'echo \'[{"name":"notejam","imageUri":"\'$DOCKER_IMG\'"}]\' > imagedefinitions.json'
        ]

        build_proj = PipelineProject(
            self, "NotejamApp",
            environment=BuildEnvironment(
                build_image=LinuxBuildImage.STANDARD_5_0,
                privileged=True
            ),
            timeout=Duration.minutes(10),
            build_spec=BuildSpec.from_object({
                "version": "0.2",
                "run-as": "root",
                "phases": {
                    "build": {
                        "commands": build_commands
                    }
                },
                "artifacts": {
                    "name": "image-definistions.zip",
                    "files": [
                        "imagedefinitions.json"
                    ]
                },
            })
        )
        build_proj.role.add_managed_policy(
            ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryPowerUser")
        )
        build_proj.role.add_managed_policy(
            ManagedPolicy.from_aws_managed_policy_name("AmazonElasticContainerRegistryPublicReadOnly")
        )

        build_output = Artifact()
        build_action = CodeBuildAction(
            action_name="Build",
            project=build_proj,
            input=source_output,
            outputs=[build_output]
        )

        pipeline.add_stage(
            stage_name="Build",
            actions=[build_action]
        )

        # ==========================================================================================
        # Test Stage - CodePipeline

        test_proj = PipelineProject(
            self, "Test",
            environment=BuildEnvironment(
                build_image=LinuxBuildImage.STANDARD_5_0,
                privileged=True
            ),
            timeout=Duration.minutes(10),
            build_spec=BuildSpec.from_object({
                "version": "0.2",
                "run-as": "root",
                "phases": {
                    "build": {
                        "commands": [
                            "docker-compose run --rm notejam npm install",
                            "sleep 15",  # mysql needs some time to start
                            "docker-compose run --rm notejam npm run init-db -- --create-test-db",
                            "docker-compose run --rm notejam npm test"
                        ]
                    }
                }
            })
        )

        test_action = CodeBuildAction(
            action_name="Test",
            project=test_proj,
            input=source_output,
        )

        pipeline.add_stage(
            stage_name="Test",
            actions=[test_action]
        )

        # ==========================================================================================
        # DB Migrations Stage - CodePipeline

        db_migration_commands = [
            f"aws ecr get-login-password --region {self.region} | docker login --username AWS --password-stdin {ecr_repo.repository_uri}",
            f"export DOCKER_TAG={env}-$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c -8)",
            f"export DOCKER_IMG={ecr_repo.repository_uri}:$DOCKER_TAG",
            f"export SECRET=$(aws secretsmanager get-secret-value --secret-id {aurora.secret.secret_name} --output text --query 'SecretString')",
            "echo DB_HOST=$(echo $SECRET | jq -r '.host') > docker.env",
            "echo DB_NAME=$(echo $SECRET | jq -r '.dbname') >> docker.env",
            "echo DB_USERNAME=$(echo $SECRET | jq -r '.username') >> docker.env",
            "echo DB_PASSWORD=$(echo $SECRET | jq -r '.password') >> docker.env",
            "docker run --rm --env-file docker.env $DOCKER_IMG npm run init-db",
        ]

        db_migrations_proj = PipelineProject(
            self, "DbMigrations",
            environment=BuildEnvironment(
                build_image=LinuxBuildImage.STANDARD_5_0,
                privileged=True
            ),
            vpc=vpc,
            subnet_selection=SubnetSelection(subnet_group_name="Persistence"),
            security_groups=[code_build_security_group],
            timeout=Duration.minutes(10),
            build_spec=BuildSpec.from_object({
                "version": "0.2",
                "run-as": "root",
                "phases": {
                    "build": {
                        "commands": db_migration_commands
                    }
                }
            })
        )
        db_migrations_proj.role.add_managed_policy(
            ManagedPolicy.from_aws_managed_policy_name("AmazonEC2ContainerRegistryReadOnly")
        )
        aurora.secret.grant_read(db_migrations_proj.role)

        db_migrations_action = CodeBuildAction(
            action_name="DbMigrations",
            project=db_migrations_proj,
            input=source_output,
        )

        pipeline.add_stage(
            stage_name="DbMigrations",
            actions=[db_migrations_action]
        )

        # ==========================================================================================
        # Deploy Stage - CodePipeline

        pipeline.add_stage(
            stage_name="Deploy",
            actions=[
                EcsDeployAction(
                    action_name="DeployAction",
                    service=service,
                    input=build_output,
                    deployment_timeout=Duration.minutes(10)
                )
            ]
        )
