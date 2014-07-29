#!/bin/bash

#删除OpenJdk
rpm -e --nodeps tzdata-java-2012c-1.el6.noarch
rpm -e --nodeps java-1.6.0-openjdk-1.6.0.0-1.45.1.11.1.el6.x86_64

#下载和安装1.8版本的Jdk
wget -P /usr/local/ --no-check-certificate --no-cookies --header "Cookie: oraclelicense=accept-securebackup-cookie" http://download.oracle.com/otn-pub/java/jdk/8u11-b12/jdk-8u11-linux-x64.rpm -O jdk-8u11-linux-x64.rpm
rpm -ivh jdk-8u11-linux-x64.rpm

echo >> /etc/profile
echo export JAVA_HOME=/usr/java/jdk1.8.0_11 >> /etc/profile
echo export JRE_HOME=/usr/java/jdk1.8.0_11/jre >> /etc/profile
echo export PATH=$PATH:$JAVA_HOME/bin:$JRE_HOME/bin >> /etc/profile
echo export CLASSPATH=.:$CLASSPATH:$JAVA_HOME/lib:$JRE_HOME/lib >> /etc/profile
source /etc/profile

#eclipse安装
wget -P /opt http://www.eclipse.org/downloads/download.php?file=/technology/epp/downloads/release/luna/R/eclipse-standard-luna-R-linux-gtk-x86_64.tar.gz&mirror_id=1093
cd /opt
mkdir eclipse
tar -zxvf eclipse-standard-luna-R-linux-gtk-x86_64.tar.gz


#Mysql安装
wget -c http://dev.mysql.com/get/Downloads/MySQL-5.5/MySQL-server-5.5.30-1.el6.x86_64.rpm/from/http://mysql.spd.co.il/
wget -c http://dev.mysql.com/get/Downloads/MySQL-5.5/MySQL-client-5.5.30-1.el6.x86_64.rpm/from/http://mysql.spd.co.il/
wget -c http://dev.mysql.com/get/Downloads/MySQL-5.5/MySQL-devel-5.5.30-1.el6.x86_64.rpm/from/http://mysql.spd.co.il/

yum -y remove mysql-libs-5.1.61-4.el6.x86_64

rpm -ivh MySQL-server-5.5.30-1.el6.x86_64.rpm
rpm -ivh MySQL-client-5.5.30-1.el6.x86_64.rpm
rpm -ivh MySQL-devel-5.5.30-1.el6.x86_64.rpm

service mysql start

mysqladmin -u root password 123456

cp /usr/share/mysql/my-medium.cnf /etc/my.cnf
sed -i '/\[client\]/a\default-character-set = utf8' /etc/my.cnf
sed -i '/\[mysqld\]/a\character-set-server = utf8' /etc/my.cnf
