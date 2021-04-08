import boto3
from netaddr import IPNetwork, cidr_merge, cidr_exclude
from faker import Faker


dynamodbTableName = "dev_vpc_cidr"
dynamodbPrimaryKey = "iad_id"
dynamodb = boto3.resource('dynamodb')


iad_platform = "iad"
iad_region = "na"
iad_environment = "dev_iad"
vpc_masks = 8
iad_id = "{0}/{1}/{2}".format(iad_platform, iad_region, iad_environment)

# Getting all value from 'vpc_cidr' filed in DynamoDB. 
def getCidrDDB(dynamodbTableName):
    table = dynamodb.Table(dynamodbTableName)
    cidrs = table.scan()['Items']
    list_of_cidr = []
    for _ in cidrs: 
        list_of_cidr.append(_['vpc_cidr'])
    return list_of_cidr

#Generate random CIDR
def GeneratorRandomCidr(dynamodbTableName, vpc_masks):
    fake = Faker()
    vpc_cidr = str(IPNetwork(fake.ipv4_private()+'/{0}'.format(vpc_masks)).cidr)
    while vpc_cidr in getCidrDDB(dynamodbTableName):
        vpc_cidr = str(IPNetwork(fake.ipv4_private()+'/{0}'.format(vpc_masks)).cidr)
    return vpc_cidr

# Check if IP belongs to the network
def check_vpc(dynamodbTableName, iad_id):
    try:
        table = dynamodb.Table(dynamodbTableName)
        item = table.get_item(Key={'iad_id': iad_id})['Item']
        return item
    except Exception as ex:
        return None


##########
# STEP 1 #
##########
# if vpc exist in DynamoDB, otherwise will create
if check_vpc(dynamodbTableName, iad_id):
    vpc_network = check_vpc(dynamodbTableName, iad_id)
    print(vpc_network)
    #class IPSplitter
else:
    vpc_cidr = GeneratorRandomCidr(dynamodbTableName, vpc_masks)
    
