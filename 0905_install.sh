#!/bin/bash

#安装OpenJdk
rpm -qa java | awk '{print "rpm -e --nodeps $0" | "bash"}'
rpm -ivh jdk-8u11-linux-x64.rpm

#配置环境变量
echo >> /etc/profile
echo export JAVA_HOME=/usr/java/jdk1.8.0_11 >> /etc/profile
echo export JRE_HOME=/usr/java/jdk1.8.0_11/jre >> /etc/profile
echo export PATH=$PATH:$JAVA_HOME/bin:$JRE_HOME/bin >> /etc/profile
echo export CLASSPATH=.:$JAVA_HOME/lib/dt.jar:$JAVA_HOME/lib/tools.jar:$JRE_HOME/lib >> /etc/profile
source /etc/profile

rpm -qa mysql | awk '{print "rpm -e --nodeps $0" | "bash"}'

rpm -ivh MySQL-server-5.5.30-1.el6.x86_64.rpm
rpm -ivh MySQL-client-5.5.30-1.el6.x86_64.rpm
rpm -ivh MySQL-devel-5.5.30-1.el6.x86_64.rpm
rpm -ivh MySQL-shared-5.5.30-1.el6.x86_64.rpm

service mysql start

mysqladmin -u root password 123456

cp /usr/share/mysql/my-medium.cnf /etc/my.cnf
sed -i '/\[client\]/a\default-character-set = utf8' /etc/my.cnf
sed -i '/\[mysqld\]/a\character-set-server = utf8' /etc/my.cnf
