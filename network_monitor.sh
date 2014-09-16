#!/bin/bash

function get_date(){
    date "+%Y-%m-%d %H:%M:%S"
}


function ping_test(){
    if [ $# -lt 1 ];
    then
        echo "Function Usage: ping_test host"
        exit 1
    fi
    
    echo `get_date` "ping $1 with 10 packages"

    host=$1
    loss_rate=`ping -c10 $host | egrep -o "[0-9]{1,3}%" | cut -d "%" -f1`

    if [ ! $loss_rate ];
    then
        echo `get_date` "Unknown host name or other network error!"
        return 1
    else
        echo `get_date` "Loss rate of packages is $loss_rate%"
        
        if [ $loss_rate -gt 50 ];
        then
            return 1
        fi
        return 0
    fi
}


function get_pid(){
    if [ $# -lt 1 ];
    then
        echo "Function Usage: get_pid command"
        exit 1
    fi

    pid=`jps | grep $1 | head -n 1 | awk '{print $1}'`

    if [ ! $pid ];
    then
        echo `get_date` "Error at function get_pid(). No such process $1"
        return 1
    fi

    echo $pid
    return 0
}


function start_process(){
    if [ $# -lt 2 ];
    then
        echo "Function Usage: start_process full_command process_name"
        exit 1
    fi

    full_command=$1
    process_name=$2
    
    $full_command

    jps | grep $process_name >/dev/null
    if [ $? -eq 0 ];
    then
        echo `get_date` "Start process $full_command sucessfully"
        return 0
    else
        echo `get_date` "Failed to start $full_command"
        return 1
    fi
}


function kill_process(){
    if [ $# -lt 1 ];
    then
        echo "Function Usage: kill_process command"
        exit 1
    fi
    
    pid=`get_pid $1`
    
    if [ $? -eq 1 ];
    then
        echo `get_date` "Process $1 has been already killed"
        return 1
    fi

    kill -9 $pid 
    if [ $? -eq 0 ];
    then
        echo `get_date` "Kill process $1 sucessfully"
        return 0
    else
        echo `get_date` "Fail to kill process $1"
        return 1
    fi
}


function check_all_related_processes(){
    node_process="GooglePlusCrawlerNode.jar"           #FacebookCrawlerNode.jar
    server_process="GooglePlusCrawlerServer.jar"       #FacebookCrawlerServer.jar
    activemq_process="activemq.jar"                    #activemq.jar

    start_activemq_cmd="/home/zhengkj/code/shell/crawler/build/StartActiveMQ.sh"
    start_server_cmd="/home/zhengkj/code/shell/crawler/build/StartServer.sh"
    start_node_cmd="/home/zhengkj/code/shell/crawler/build/StartNode.sh"
    
    get_pid $activemq_process >/dev/null
    if [ $? -eq 0 ];
    then
        echo `get_date` "ActiveMQ is running"
    else
        echo `get_date` "ActiveMQ is not running! Try to start ActiveMQ!"
        start_process $start_activemq_cmd $activemq_process
    fi

    get_pid $server_process > /dev/null
    if [ $? -eq 0 ];
    then
        echo `get_date` "CrawlerServer is running"
    else
        echo `get_date` "CrawlerServer is not running! Try to start CrawlerServer"
        start_process $start_server_cmd $server_process
    fi

    get_pid $node_process > /dev/null
    if [ $? -eq 0 ];
    then
        echo `get_date` "CrawlerNode is running"
    else
        echo `get_date` "CrawlerNode is not running! Try to start CrawlerNode"
        start_process $start_node_cmd $node_process
    fi
}


function kill_all_related_processes(){
    node_process="GooglePlusCrawlerNode.jar"           #FacebookCrawlerNode.jar
    server_process="GooglePlusCrawlerServer.jar"       #FacebookCrawlerServer.jar
    activemq_process="activemq.jar"                    #activemq.jar
    
    kill_process $node_process 2>&1
    kill_process $server_process 2>&1
    kill_process $activemq_process 2>&1
}


function main(){
    while true;
    do
        ping_test "plus.google.com"
        if [ $? -eq 0 ];
        then
            echo `get_date` "Network works normally"
            check_all_related_processes
        else
            echo `get_date` "Network cannot work"
            echo `get_date` "Try to kill all related processes"
            kill_all_related_processes
        fi
        
        echo 
        sleep $sleep_time
    done
}


sleep_time=60
main
