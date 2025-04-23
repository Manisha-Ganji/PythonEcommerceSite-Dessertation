from datetime import datetime, timezone
import boto3

# --- REGION CONFIG ---
PRIMARY_REGION = 'us-east-1'
SECONDARY_REGION = 'us-west-1'

# --- DNS CONFIG ---
PRIMARY_ALB_DNS = 'eCommAppLoadBalancer-1629063426.us-east-1.elb.amazonaws.com'
SECONDARY_ALB_DNS = 'eCommAppLoadBalancer-Secondary-2144717324.us-west-1.elb.amazonaws.com'
HOSTED_ZONE_ID = 'Z00780922145L3VLDJ1AQ'
RECORD_NAME = 'OnlineBookStore.ecommappdomains.com.'

# --- RESOURCE IDENTIFIERS ---
PRIMARY_RDS_IDENTIFIER = 'ecommappdbprimary'
PRIMARY_ASG_NAME = 'ECommAppEC2ASG'
PRIMARY_S3_NAME = 'ecommerce-product-images-primary'
PRIMARY_ALB_ARN = 'arn:aws:elasticloadbalancing:us-east-1:343218219620:loadbalancer/app/eCommAppLoadBalancer/04a47aff26647f64'
PRIMARY_TARGET_GROUP_ARN = 'arn:aws:elasticloadbalancing:us-east-1:343218219620:targetgroup/ECommAppALBtargetGrp/c36647b6f18d14db'

# Store timestamps in memory (temporary - per Lambda run)
failover_timestamp = None

def lambda_handler(event, context):
    global failover_timestamp

    print("🔁 Lambda triggered.")
    current_target = get_current_alb_target()
    print(f"🔍 Current ALB target: {current_target}")

    any_failure = (
        not check_rds(PRIMARY_REGION) or
        not check_s3(PRIMARY_REGION) or
        not check_ec2(PRIMARY_REGION) or
        not check_asg(PRIMARY_REGION) or
        not check_alb(PRIMARY_REGION)
    )

    if any_failure:
        print("One or more primary services failed.")
        if SECONDARY_ALB_DNS.lower() not in current_target:
            update_route53(SECONDARY_ALB_DNS)
            failover_timestamp = datetime.now(timezone.utc)
            print(f"Failover triggered at: {failover_timestamp.isoformat()}")
        else:
            print("Already pointing to secondary ALB.")
    else:
        print("All primary services are healthy.")
        if PRIMARY_ALB_DNS.lower() not in current_target:
            update_route53(PRIMARY_ALB_DNS)
            recovery_time = datetime.now(timezone.utc)
            print(f"Recovery triggered at: {recovery_time.isoformat()}")
            if failover_timestamp:
                downtime = (recovery_time - failover_timestamp).total_seconds()
                print(f"Total failover duration: {downtime} seconds")
            else:
                print("Failover timestamp not found (was probably in a previous Lambda run).")
        else:
            print("Already pointing to primary ALB. No change.")



# --- HEALTH CHECKS ---
def check_rds(region):
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances(DBInstanceIdentifier=PRIMARY_RDS_IDENTIFIER)
        db_status = response['DBInstances'][0]['DBInstanceStatus']
        
        if db_status == 'available':
            print(f"RDS instance status is '{db_status}' (available).")
            return True
        else:
            print(f"RDS instance status is '{db_status}' (not available).")
            return False
    except Exception as e:
        print(f"RDS health check failed: {e}")
        return False

def check_s3(region):
    try:
        s3 = boto3.client('s3', region_name=region)
        response = s3.list_objects_v2(Bucket=PRIMARY_S3_NAME, MaxKeys=1)
        
        # Check if the call was successful (no exception thrown) and bucket is accessible
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            print(f"S3 health check passed: response code {response['ResponseMetadata']['HTTPStatusCode']}")
            return True
        else:
            print(f"S3 health check failed: Unexpected response code {response['ResponseMetadata']['HTTPStatusCode']}")
            return False
    except Exception as e:
        print(f"S3 health check failed: {e}")
        return False

def check_ec2(region):
    try:
        # Get EC2 instance IDs from the ASG
        asg = boto3.client('autoscaling', region_name=region)
        group = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[PRIMARY_ASG_NAME])['AutoScalingGroups'][0]
        instance_ids = [inst['InstanceId'] for inst in group['Instances']]

        if not instance_ids:
            print("No instances found in ASG.")
            return False

        # Now check the instance states
        ec2 = boto3.client('ec2', region_name=region)
        statuses = ec2.describe_instance_status(InstanceIds=instance_ids, IncludeAllInstances=True)['InstanceStatuses']

        for inst in statuses:
            if inst['InstanceState']['Name'] != 'running':
                print(f"EC2 instance {inst['InstanceId']} is {inst['InstanceState']['Name']}")
                return False
            else:
                print(f"EC2 instance {inst['InstanceId']} is {inst['InstanceState']['Name']}.")
        return True
    except Exception as e:
        print(f"EC2 health check failed: {e}")
        return False

def check_asg(region):
    try:
        asg = boto3.client('autoscaling', region_name=region)
        group = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[PRIMARY_ASG_NAME])['AutoScalingGroups'][0]
        if len(group['Instances']) >= group['DesiredCapacity']:
            print(f"ASG health check passed. Number of instances running: {len(group['Instances'])}")
            return True
        else:
            print(f"ASG health check failed. Number of instances running: {len(group['Instances'])}")
            return False
    except Exception as e:
        print(f"ASG health check failed: {e}")
        return False

def check_alb(region):
    try:
        elbv2 = boto3.client('elbv2', region_name=region)
        lb = elbv2.describe_load_balancers(LoadBalancerArns=[PRIMARY_ALB_ARN])['LoadBalancers'][0]
        if lb['State']['Code'] != 'active':
            print(f"ALB health check failed: Load balancer state {lb['State']['Code']}")
            return False
        ths = elbv2.describe_target_health(TargetGroupArn=PRIMARY_TARGET_GROUP_ARN)['TargetHealthDescriptions']
        for th in ths:
            if th['TargetHealth']['State'] != 'healthy':
                print(f"ALB health check failed: Target group health status: {th['TargetHealth']['State']}")
                return False
            else:
                print(f"ALB health check passed: Target group health status: {th['TargetHealth']['State']}")
        return True
    except Exception as e:
        print(f"ALB health check failed: {e}")
        return False

# --- ROUTE 53 LOGIC ---
def get_current_alb_target():
    try:
        route53 = boto3.client('route53')
        record = route53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            StartRecordName=RECORD_NAME,
            StartRecordType='A',
            MaxItems='1'
        )['ResourceRecordSets'][0]
        return record['AliasTarget']['DNSName']
    except Exception as e:
        print(f"Failed to get current ALB from Route 53: {e}")
        return None

def update_route53(alb_dns):
    region = SECONDARY_REGION if alb_dns == SECONDARY_ALB_DNS else PRIMARY_REGION
    zone_id = get_alb_zone_id(region)

    route53 = boto3.client('route53')
    route53.change_resource_record_sets(
        HostedZoneId=HOSTED_ZONE_ID,
        ChangeBatch={
            'Comment': f'Switching ALB to {alb_dns}',
            'Changes': [
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': RECORD_NAME,
                        'Type': 'A',
                        'AliasTarget': {
                            'HostedZoneId': zone_id,
                            'DNSName': alb_dns,
                            'EvaluateTargetHealth': False
                        }
                    }
                }
            ]
        }
    )

def get_alb_zone_id(region):
    try:
        elbv2 = boto3.client('elbv2', region_name=region)
        lbs = elbv2.describe_load_balancers()['LoadBalancers']
        return lbs[0]['CanonicalHostedZoneId']  # Assumes 1 ALB per region
    except Exception as e:
        print(f"Failed to fetch ALB Hosted Zone ID: {e}")
        raise
