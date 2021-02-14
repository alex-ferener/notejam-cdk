
# notejam-cdk

This project contains all the infrastructure necessary to deploy the 
[nodejam-express](https://github.com/alex-ferener/notejam-express)) app.

Only the initial `cdk deploy` is done manually.

After that, a CI/CD pipeline will be created for the CDK app and each commit 
on `main` branch will notify `CopePipeline` (via Webhook) which will continuously deploy the CDK app (aka Self Mutate).

Fork both repos (including [nodejam-express](https://github.com/alex-ferener/notejam-express))
and update the file [cdk.dev.env](https://github.com/alex-ferener/notejam-cdk/blob/main/cdk.dev.env) accordingly.

For the initial deployment set `MIN_CAPACITY=0` and `DESIRED_CAPACITY=0` in `cdk.dev.env` 
because of *chicken or egg* issue regarding CodePipeline and ECS. 
After CodeBuild pushes the image to ECR, you can set your desired capacity, 
and then `git commit` + `git push` to deploy the changes.

### Pre-requisites
- create a [**GitHub Access Token**](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token), 
  with scopes **repo** and **admin:repo_hook**.
- create a **Secrets Manager `Secret`** named: `notejam` in the same region you plan to deploy. It must be JSON type.
  - set `gitHubToken` as **key**, and the **value** of the GitHub Access Token

### Bootstrap your AWS environment
```
export CDK_NEW_BOOTSTRAP=1 
npx cdk bootstrap \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess \
  aws://${ACCOUNT_ID}/${REGION}
```

### Create and Activate virtualenv & Install dependencies:
```
npm install -g aws-cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Synthesize artifacts
```
./cdk-ctl.sh synth dev
```

### Deploy resources (~15 min)
```
./cdk-ctl.sh deploy dev 
```

### CDK outputs
- CI/CD Pipeline which will continuously deploy this CDK app
- VPC with 1x Public Subnet and 2x Private Subnets (all of them across 3x AZs)
- 3x NAT Gateways (one in each AZ)
- Amazon Aurora: 2x Nodes (Multi-AZ)
- ElastiCache: 2x Nodes (Multi-AZ)
- Application Load Balancer
- CloudFront Distribution
- ECR Repo
- ECS Task Definition
- ECS Service - Fargate: Min: 2x Tasks running
- Application Auto Scaling is Enabled (based on CPU Load) 
- Application Logs are sent to CloudWatch Logs
- Has support for multiple environments. Each branch can be deployed on a new env (name + account + region)  
- CI/CD Pipeline for Notejam App with 5x Stages
  - **Source** (pull code from Github triggered by Webhook)
  - **Build** (build and push the image to ECR)
  - **Test** (run application tests)
  - **DB Migrations** (run Database migrations)
  - **Deploy** (to Fargate)

### CloudFormation Outputs
- CloudFront Domain Name

### TODOs:
- [ ] **Diagram**: Infrastructure overview
- [ ] **Documentation**: Describe the benefits
- [ ] **Folder structure**: Group resources into `Constructs` and split them into multiple files
- [ ] **CloudWatch**: Centralize all metrics in a Dashboard
- [ ] **Certificate Manager**: Create Certificate and Enable HTTPS on ALB
- [ ] **AWS WAF**: Enable
- [ ] **CloudFront**: Add `CachePolicy` and additional `behaviours`
- [ ] **CloudTrail**: Enable
- [ ] **SES**: Send `Forgot Password` emails
- [ ] **App**: Cache ORM Models in Redis

### Clean-up
```
./cdk-ctl.sh destroy dev 
```

Delete is skipped for:
- AWS::S3::Bucket (artifacts)
- AWS::ECR::Repository
- AWS::Logs::LogGroup
