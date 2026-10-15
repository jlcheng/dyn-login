# Deployment

The local preview is ready without AWS. These steps are for publishing and deploying the site after the build has been accepted. The implementation workflow does not automatically commit, publish a repository, or apply Terraform.

## Infrastructure

The Terraform root module is in the existing infrastructure repository:

```sh
cd /Users/jcheng/privprjs/terraform/piles/dyn-login
```

Refresh credentials with `aws login`. Follow the infrastructure repository's credential instructions: AWS CLI uses `--profile jcheng`; Terraform runs with no `AWS_PROFILE` set.

Before applying, verify the live `ecs-alb-p` VPC matches `jc_default_vpc`, public subnets have internet access, the HTTPS listener has the issued `*.jchengdev.org` certificate, the ALB security group allows outbound TCP 8000 to the task subnets, and listener priority 9 is unused. The implementation inspected existing Terraform definitions, but live verification was blocked by an expired AWS session.

```sh
aws --profile jcheng elbv2 describe-load-balancers --names ecs-alb-p
aws --profile jcheng elbv2 describe-listeners --load-balancer-arn <alb-arn>
aws --profile jcheng elbv2 describe-rules --listener-arn <https-listener-arn>
aws --profile jcheng elbv2 describe-listener-certificates --listener-arn <https-listener-arn>
aws --profile jcheng iam list-open-id-connect-providers
```

The pile reuses an existing GitHub OIDC provider by default. If none exists, set `manage_github_oidc_provider = true` in your Terraform variables to create it in this infrastructure repository. Reused resources are data lookups; their names and tags stay managed by their existing piles. Change `listener_priority` if 9 is occupied. All project resources have `Project = dyn-login` and `ManagedBy = terraform` tags where AWS supports them.

Run the existing infrastructure drift check before and after applying:

```sh
cd /Users/jcheng/privprjs/terraform
uv run python scripts/check-all.py
terraform -chdir=piles/dyn-login init
terraform -chdir=piles/dyn-login plan -out=dyn-login.tfplan
terraform -chdir=piles/dyn-login apply dyn-login.tfplan
```

The initial service has zero tasks so bootstrap does not depend on an unpublished image or an unpopulated signing-key secret. The DNS route will return an unavailable response until bootstrap completes. Fargate tasks use the existing public subnets and receive public IPs for outbound AWS API access. Inbound application access is restricted to the existing ALB. This avoids adding a NAT gateway for one small service.

## Signing key

After Terraform has created the Secrets Manager secret, populate it once through fnox, without printing the value:

```sh
cd /Users/jcheng/pubprjs/dyn-login
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))' \
  | fnox --non-interactive --no-daemon set SESSION_SIGNING_KEY
```

Keep this key stable across deployments. Changing it invalidates all sessions. The task role reads only the application's configuration table and signing secret; the execution role pulls images and writes container logs.

## Public repository and first image

Create public repository `jlcheng/dyn-login` on branch `main`, then commit the app and connect the local repository when publication is authorized. Set its `AWS_DEPLOY_ROLE_ARN` repository variable to the `github_deploy_role_arn` Terraform output. The deploy role trusts only `repo:jlcheng/dyn-login:ref:refs/heads/main` with audience `sts.amazonaws.com`.

Bootstrap the first image before increasing the desired task count:

```sh
cd /Users/jcheng/pubprjs/dyn-login
aws --profile jcheng ecr get-login-password --region us-west-2 \
  | docker login --username AWS --password-stdin 117014118018.dkr.ecr.us-west-2.amazonaws.com

docker build --platform linux/amd64 \
  -t 117014118018.dkr.ecr.us-west-2.amazonaws.com/dyn-login:bootstrap .
docker push 117014118018.dkr.ecr.us-west-2.amazonaws.com/dyn-login:bootstrap
```

Set `desired_count = 1` in the pile's Terraform variables and apply a saved plan. Keep that value set for later applies. Terraform ignores later task-definition updates made by GitHub Actions so infrastructure applies do not roll back the deployed app.

```sh
aws --profile jcheng ecs wait services-stable --cluster dyn-login --services dyn-login
uv run python scripts/smoke.py https://dyn-login.jcheng.org
```

Subsequent pushes to `main` validate and deploy automatically. Pull requests only validate. Deployments fail if ECS rolls back to a different revision, has zero running tasks, fails health verification, or cannot complete configure, login, profile, and logout over HTTPS.

## Local infrastructure checks

These need no AWS credentials and do not change cloud resources:

```sh
terraform -chdir=/Users/jcheng/privprjs/terraform/piles/dyn-login init -backend=false
terraform -chdir=/Users/jcheng/privprjs/terraform/piles/dyn-login fmt -check -recursive
terraform -chdir=/Users/jcheng/privprjs/terraform/piles/dyn-login validate
terraform -chdir=/Users/jcheng/privprjs/terraform/piles/dyn-login test
```

The Terraform test uses a mock AWS provider. Its simulated apply verifies service, storage, IAM trust, tags, and fnox startup settings without contacting AWS.
