import logging
import os

from carthage import *
from carthage.modeling import *
from carthage.config import ConfigLayout
from carthage.dependency_injection import *

import boto3
from botocore.exceptions import ClientError

__all__ = ['AwsConnection', 'AwsManaged']


@inject_autokwargs(config = ConfigLayout, injector = Injector)
class AwsManaged(AsyncInjectable, SetupTaskMixin):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @memoproperty
    def stamp_descriptor(self):
        raise NotImplementedError(type(self))

    @memoproperty
    def stamp_path(self):
        p = self.config.state_dir
        p = os.path.join(p,"aws_stamps", self.stamp_type)
        p += ".stamps"
        os.makedirs(p, exist_ok=True)
        return p


@inject(config = ConfigLayout, injector = Injector)
class AwsConnection(AwsManaged):

    def __init__(self, config, injector):
        self.config = config.aws
        self.injector = injector
        super().__init__()
        self.connection = None
        self.connection = boto3.Session(
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key
        )
        self.region = self.config.region
        self.client = self.connection.client('ec2', region_name=self.region)
        self.keys = []
        for key in self.client.describe_key_pairs()['KeyPairs']:
            self.keys.append(key['KeyName'])
        self.vpcs = []
        self.igs = []
        self.subnets = []
        self.inventory()

    def inventory(self):
        r = self.client.describe_vpcs()
        for v in r['Vpcs']:
            vpc = {'id': v['VpcId']}
            if 'Tags' in v:
                for t in v['Tags']:
                    if t['Key'] == 'Name':
                        vpc['name'] = t['Value']
            else: vpc['name'] = ''
            self.vpcs.append(vpc)

        r = self.client.describe_internet_gateways()
        for ig in r['InternetGateways']:
            if len(ig['Attachments']) == 0:
                continue
            a = ig['Attachments'][0]
            if a['State'] == 'attached' or a['State'] == 'available':
                self.igs.append({'id': ig['InternetGatewayId'], 'vpc': a['VpcId']})

        r = self.client.describe_subnets()
        for s in r['Subnets']:
            subnet = {'CidrBlock': s['CidrBlock'], 'id': s['SubnetId'], 'vpc': s['VpcId']}
            self.subnets.append(subnet)

        