#!/bin/bash 
# Use bash
set -e # Makes script exit upon any execution fails

# Load necessary module
# modulecmd is a script that prints stuff
# eval executes the commands that modulecmd prints
# adds sshpass (ssh authenticator using passwords) using bash
eval `/app/modules/0/bin/modulecmd bash add sshpass`
module add python/3.8

# Function to display usage information
usage() {
    echo "Usage: $0 (-i <ipaddress> | -p <podname>) [-a] [-t <timestamp>] [-j/-s <filename>] [-m <module(s)>] "
    echo " -i <ipaddress>   Use an IP address for operations"
    echo " -p <podname>     Use a Kubernetes pod name for operations"
    echo " -a               Open the result in Aether"         
    echo " -t <timestamp>   Filter events after specified time: HH:MM:SS"
    echo " -j <filename>    Save the JSON file to a specified file"
    echo " -s <filename>    Save the log to the specified file"
    echo " -m <modulenames> Separate each module with commas and no spaces: ORC,OFHCC,..."
    exit 1
}

# Function to clean up temporary files
cleanup() {
    if [ -d "$TEMP_DIR" ]; then # "-d" checks if it is a directory
        echo "Cleaning up temporary files..."
        # Remove the temporary directory
        rm -rf "$TEMP_DIR" # "-rf": "-r" = recursive deletion. "-f" = force deletion w/out confirmation 
    fi
}

# Trap to ensure cleanup is called on EXIT
# trap runs a function/sequence when a signal is given
# EXIT is the signal given when the code is exited
trap cleanup EXIT

# Initialize variables
# Moves to the absolute location of the script
# BASH_SOURCE[0] points to the path of the current script
# dirname extracts only the directory path out of everything
# pwd prints the current working directory
# $command returns the output from the command after execution
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASSWORD="root"
TEMP_DIR=$(mktemp -d) # Creates temporary directory and returns the path of the directory
JSON_FILE="$TEMP_DIR/output.json" # Points to a file in the temp directory
AETHER=false
declare -a arr;
IP_ADDRESS=""
POD_NAME=""
JSON_OUTPUT_NAME=""
TIMESTAMP=""
OUTPUT_FILENAME=""

# Parse command-line options
while getopts ":i:p:aj:s:t:m:" opt; do
    case $opt in
        i) IP_ADDRESS="$OPTARG"
        ;;
        p) POD_NAME="$OPTARG"
        ;;
        a) AETHER=true
        ;;
        j) JSON_OUTPUT_DIR="$OPTARG"
        ;;
        t) TIMESTAMP="$OPTARG"
        ;;
        s) OUTPUT_FILENAME="$OPTARG"
        ;;
        m) readarray -td, arr <<<"$OPTARG, "; unset 'arr[-1]'; declare -p arr;
		;;
        \?) echo "Invalid option -$OPTARG" >&2 # >& ends the command 
            usage
        ;;
        :) echo "Option -$OPTARG requires an argument." >&2
            usage
        ;;
    esac
done

# ORC: /tmp/applicationtmp/CAT-ORC-CNEE_CXP2021561_1/DASH_1/.ship
# OFHCC: /tmp/applicationtmp/OFHCC-CNEE_CXP2021501_1/.ship
# OFHRRC: /tmp/applicationtmp/OFHRRC-CNEE_CXP2021479_1/.ship

# Check for mutual exclusivity of -i and -p
if [ -n "$IP_ADDRESS" ] && [ -n "$POD_NAME" ]; then # "-n" checks if the string is not empty
# If both have values...
    echo "Options -i and -p are mutually exclusive."
    usage
elif [ -z "$IP_ADDRESS" ] && [ -z "$POD_NAME" ]; then # "-z" checks if the string is empty
# If both are empty...
    usage
fi

if [ -n "$IP_ADDRESS" ]; then # If IP address is provided...

    if [ -n "$arr" ]; then # Modules provided
        for path in $arr; do
	    
            DIRECTORY=$(oc exec $POD_NAME -- find /tmp/applicationtmp -name "*$path*" -type d)
	    
            if [ -z "$(oc exec $POD_NAME -- ls $DIRECTORY)" ]; then
                echo "$DIRECTORY does not exist or is empty."
                continue;
            fi
	    
            FILES=$(oc exec $POD_NAME -- find $DIRECTORY -name "*.ship")
	    
            for FILE in $FILES; do # Loop through all files ending in .whip
                REMOTE_PATH="root@$IP_ADDRESS:$FILE"
                sshpass -p "$PASSWORD" scp $REMOTE_PATH "$TEMP_DIR" 
                
                sshpass -p "$PASSWORD" ssh root@${IP_ADDRESS} "um list" > "$TEMP_DIR/mailboxes.txt"
            done
        done
    else # Other logs
        REMOTE_PATH="root@$IP_ADDRESS:/tmp/applicationtmp/*/*.ship.whip" # Path to the remote file, includes all files ending in .ship.whip
        
        # Copies the file to the temp directory
        sshpass -p "$PASSWORD" scp $REMOTE_PATH "$TEMP_DIR"  # Uses sshpass to get password for scp command
        # Executes "um list" in remote VDI using ssh
        sshpass -p "$PASSWORD" ssh root@${IP_ADDRESS} "um list" > "$TEMP_DIR/mailboxes.txt" # Directs output from remote to local file in temp directory
    fi
elif [ -n "$POD_NAME" ]; then # If pod name provided...

    FILES=()

    if [ -n "$arr" ]; then # Modules provided
        for path in ${arr[@]}; do
            DIRECTORY=$(oc exec $POD_NAME -- find /tmp/applicationtmp -name "*$path*" -type d)
	    
            if [ -z "$(oc exec $POD_NAME -- ls $DIRECTORY)" ]; then
                echo "$DIRECTORY does not exist or is empty."
                continue;
            fi
            FILES+=($(oc exec $POD_NAME -- find $DIRECTORY -name "*.ship"))
        done
    else # Other logs
        FILES=$(oc exec $POD_NAME -- find /tmp -name "*.whip") # Finds the files inside a Kubernetes pod
    fi
    
    for FILE in ${FILES[@]}; do # Loop through all files ending in .whip
        echo "copying file $FILE" 
        file_name=$(basename $FILE) # Extracts the file name using basename
        oc cp ${POD_NAME}:${FILE} $TEMP_DIR/$file_name # Copies the file into local temp dir with the same nam
        echo "done!"
    done
    echo "copy mailboxes"
    oc exec $POD_NAME -- um list > $TEMP_DIR/mailboxes.txt # Executes um list in pod and directs output into temp director
fi

if $AETHER; then
    if [ -n "$arr" ]; then
        echo "Options '-m' cannot be used with '-a'"
        usage
    else 
        if [ ! -e ${HOME}/.shipitrc ]; then # The file does not exist
            ${DIR}/shipit --login # Login to shipit
        fi
        ${DIR}/shipit $TEMP_DIR/*.whip -m $TEMP_DIR/mailboxes.txt --aether # Other shipit functions
    fi
fi

    ls -A $TEMP_DIR
# Expand DIR (go to directory and then open shipit)
# TEMP_DIR is a command (see var init): makes temporary files
# Redirects stdout into the provided json file
if [ -n "$arr" ]; then
    ${DIR}/ship.py $TEMP_DIR/*.ship --mailboxes $TEMP_DIR/mailboxes.txt --signals ${DIR}/signal_list --json > $JSON_FILE
else
    ${DIR}/shipit $TEMP_DIR/*.whip -m $TEMP_DIR/mailboxes.txt > $JSON_FILE
fi

# Copy JSON file to the specified directory if provided
if [ -n "$JSON_OUTPUT_DIR" ]; then
    cp $JSON_FILE "$JSON_OUTPUT_NAME"
    echo "JSON file copied to $JSON_OUTPUT_NAME"
fi

# Using different python scripts for ORC/OFHCC/OFHRRC displays
python_script="${DIR}/present_shipit_json.py $JSON_FILE -p -n"
if [ -n "$arr" ]; then
    python_script="${DIR}/present_shipit_json_orc.py $JSON_FILE -i -g -n"
fi

# Sort for timestamp
time=''
if [ -n "$TIMESTAMP" ]; then
    time="-t $TIMESTAMP"
fi

if [ -n "$OUTPUT_FILENAME" ]; then # Output to be saved externally
    python3 $python_script $time > "temp_output.txt" # Redirect script output into specified output
    python3 ${DIR}/clean_log.py "$OUTPUT_FILENAME" # Clean up ASCII characters and store clean output
    rm temp_output.txt
    echo "Output saved to $OUTPUT_FILENAME"
else
    python3 $python_script $time
fi

# Cleanup will be handled by the trap on EXIT
