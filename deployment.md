# Deployment

Production runs at https://dyn-login.jcheng.org, with the JSON editor at https://dyn-login.jcheng.org/editor. Source is published at https://github.com/jlcheng/dyn-login; pushes to main validate and deploy through GitHub Actions.

## Infrastructure

The Terraform root module is in the existing infrastructure repository:

```sh
cd /Users/jcheng/privprjs/terraform/piles/dyn-login
```

Refresh credentials with `aws login`. Follow the infrastructure repository's credential instructions: AWS CLI uses `--profile jcheng`; Terraform runs with no `AWS_PROFILE` set.

The service reuses `ecs-alb-p`, the `jc_default_vpc` public subnets, and the HTTPS listener. These were verified during deployment, including ALB outbound access and listener priority 9. The dyn-login pile owns a DNS-validated ACM certificate for `dyn-login.jcheng.org`, its SNI attachment to the shared listener, and DNS records in the existing jcheng.org zone.

```sh
aws --profile jcheng elbv2 describe-load-balancers --names ecs-alb-p
aws --profile jcheng elbv2 describe-listeners --load-balancer-arn <alb-arn>
aws --profile jcheng elbv2 describe-rules --listener-arn <https-listener-arn>
aws --profile jcheng elbv2 describe-listener-certificates --listener-arn <https-listener-arn>
aws --profile jcheng iam list-open-id-connect-providers
```

The account had no GitHub OIDC provider at bootstrap, so `terraform.tfvars` sets `manage_github_oidc_provider = true` and this pile owns it. If reusing a provider in a different account, set this to false. Reused resources are data lookups; their names and tags stay managed by their existing piles. Change `listener_priority` if 9 is occupied. All project resources have `Project = dyn-login` and `ManagedBy = terraform` tags where AWS supports them.

Run the existing infrastructure drift check before and after applying:

```sh
cd /Users/jcheng/privprjs/terraform
uv run python scripts/check-all.py
terraform -chdir=piles/dyn-login init
terraform -chdir=piles/dyn-login plan -var='desired_count=0' -out=dyn-login.tfplan
terraform -chdir=piles/dyn-login apply dyn-login.tfplan
```

Use the zero-task override above only for a first bootstrap. The checked-in variables set one task for normal operation. A zero-task bootstrap avoids depending on an unpublished image or unpopulated signing-key secret. The DNS route will return an unavailable response until bootstrap completes. Fargate tasks use the existing public subnets and receive public IPs for outbound AWS API access. Inbound application access is restricted to the existing ALB. This avoids adding a NAT gateway for one small service.

## Signing key

After Terraform has created the Secrets Manager secret, populate it once through fnox, without printing the value:

```sh
cd /Users/jcheng/pubprjs/dyn-login
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))' \
  | AWS_PROFILE=jcheng fnox --non-interactive --no-daemon set SESSION_SIGNING_KEY
```

Keep this key stable across deployments. Changing it invalidates all sessions. The task role reads only the application's configuration table and signing secret; the execution role pulls images and writes container logs.

## Public repository and first image

The public repository is `jlcheng/dyn-login` on branch `main`. Its `AWS_DEPLOY_ROLE_ARN` repository variable is set to the `github_deploy_role_arn` Terraform output. The deploy role trusts only `repo:jlcheng/dyn-login:ref:refs/heads/main` with audience `sts.amazonaws.com`.

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
