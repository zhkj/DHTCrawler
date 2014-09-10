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
        echo `get_date` "Loss rate is $loss_rate%"
        
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

    pid=`jps | grep $1 | head -n 1 | awk {print $1}`

    if [ ! $pid ];
    then
        echo `get_date` "Error at function get_pid(). No such process $1"
        return 1
    fi

    echo $pid
    return 0
}


function start_process(){
    if [ $# -lt 1 ];
    then
        echo "Function Usage: start_process full_command"
        exit 1
    fi

    full_command=$1
    
    $full_command
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


function kill_all_related_processes(){
    start_node_process="GooglePlusCrawlerNode.jar"           #FacebookCrawlerNode.jar
    start_server_process="GooglePlusCrawlerServer.jar"       #FacebookCrawlerServer.jar
    start_activemq_process="activemq.jar"                    #activemq.jar
    
    kill_process $start_node_process
    kill_process $start_server_process
    kill_process $start_activemq_process
}


function restart_all_related_processes(){     
    start_activemq_cmd="/home/jiangbo/build/StartActiveMQ.sh"
    start_node_cmd="/home/jiangbo/build/StartNode.sh"
    start_server_cmd="/home/jiangbo/build/StartServer.sh"

    start_process $start_activemq_cmd
    start_process $start_server_cmd
    start_process $start_node_cmd
}


function main(){
    while true;
    do
        ping_test "plus.google.com"
        if [kill $? -eq 0 ];
        then
            echo `get_date` "Network works normally"
        else
            echo `get_date` "Network cannot work"
            echo `get_date` "Try to kill all related processes"
            kill_all_related_processes
            echo `get_date` "Try to restart all related processes"
            restart_all_processes
        fi

        sleep $sleep_time
    done
}

sleep_time=5
main
