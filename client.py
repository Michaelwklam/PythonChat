#! /usr/bin/python

# Written by Michael for COMP3331 assignment 1
# client.py

import sys
import select
import logging
import threading
from socket import *


if(len(sys.argv) < 3) :
    print 'Usage : python client.py serverIP serverPort'
    sys.exit()

if (len(sys.argv) > 3) and sys.argv[3] == '-d':
    logging.basicConfig(level=logging.DEBUG)

#server defines
server_IP = str(sys.argv[1]);
server_port = int(sys.argv[2]);

#additional config
RECV_BUFFER = 4096 
sys.tracebacklimit=0

# client states
STATE_USERNAME = 1
STATE_PASSWORD = 2
STATE_AWAITING_VALIDATION = 3
STATE_BLOCKED = 4
STATE_AUTHENTICATED = 5

#client config
myState = 0
global myUsername
running_threads = {}

#p2p config
SOCKET_LIST = []
USER_MAP_TO_SOCKET = {}
SOCKET_MAP_TO_USER = {}

# function for the p2p listening thread
# accepts incoming connections from other clients using TCP
def p2p_Listener():
    global p2pSocket
    global myp2pPort

    # setup socket
    p2pSocket = socket(AF_INET, SOCK_STREAM)
    p2pSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    p2pSocket.bind(('', 0))
    p2pSocket.listen(10)

    SOCKET_LIST.append(p2pSocket)
    logging.debug("p2p server started")

    myp2pPort = p2pSocket.getsockname()[1]

    while p2p_Listener in running_threads:

        # get the list sockets which are ready to be read through select
        # 4th arg, time_out  = 0 : poll and never block
        ready_to_read,ready_to_write,in_error = select.select(SOCKET_LIST,[],[],0)
      
        for sock in ready_to_read:
            # a new connection request recieved
            if sock == p2pSocket: 
                sockfd, addr = p2pSocket.accept()
                SOCKET_LIST.append(sockfd)
                logging.debug('P2P:Client (%s, %s) connected' % addr)

            # a message from a client, not a new connection
            else:
                # process data recieved from client, 
                try:
                    # receiving data from the socket.
                    data = sock.recv(RECV_BUFFER)
                    if data:
                        logging.debug('[P2P]Received ' + data + ' from' + str(sock.getpeername()))
                        handlep2pCommand(sock,data)
                    else:
                        # remove the socket that's broken    
                        if sock in SOCKET_LIST:
                            SOCKET_LIST.remove(sock)

                # exception 
                except:
                    continue

    p2pSocket.close()

#P2P connection thread
# Spawns a thread when using startprivate
def p2p_connect(userIP, userPort, user, myUser):

    logging.debug('[P2P]attempting to connect to %s IP:%s PORT:%s' % (user,userIP,userPort))

    userIP = str(userIP)
    userPort = int(userPort)

    global p2p_conn_sock
    p2p_conn_sock = socket(AF_INET, SOCK_STREAM)
    p2p_conn_sock.settimeout(5)

    # map sockets
    USER_MAP_TO_SOCKET[user] = p2p_conn_sock 
    SOCKET_MAP_TO_USER[p2p_conn_sock] = user

    # append socket for listening
    SOCKET_LIST.append(p2p_conn_sock)

    # connect to client
    try :
        p2p_conn_sock.connect((userIP, userPort))
    except :
        e = sys.exc_info()[1]
        logging.debug('P2P connection error: %s' % e)

    display('start private message with '+user)
    logging.debug('[P2P]Connected to %s' % user)

    # send identification
    p2p_conn_sock.send('<p2p_verification>'+myUser)

#main client thread
#connects to remote server for basic chat functions
def main_client():
    global clientSocket
    clientSocket = socket(AF_INET, SOCK_STREAM)
    clientSocket.settimeout(5)

    # connect to remote host (server)
    try :
        clientSocket.connect((server_IP, server_port))
    except :
        print 'Unable to connect'
        close_client()
     
    logging.debug('Connected to host')

    myState = STATE_USERNAME

    while main_client in running_threads:

        if (myState == STATE_USERNAME):
            init_Login('user')
        elif (myState == STATE_PASSWORD):
        	init_Login('pass')
        elif (myState == STATE_BLOCKED):
            close_client()
            
        socket_list = [sys.stdin, clientSocket]
        
        # Get the list sockets which are readable
        read_sockets, write_sockets, error_sockets = select.select(socket_list , [], [])
         
        for sock in read_sockets:    

            if sock == clientSocket:
                # incoming message from remote server
                data = sock.recv(RECV_BUFFER)
                if not data :
                    print '\nDisconnected from chat server'
                    close_client()
                else :
                    # handle server commands
                    myState = handleServerCmd(data)

            else: # user typing in commands
                if myState == STATE_USERNAME:
                    myUsername = sys.stdin.readline()
                    myUsername = myUsername.rstrip()
                    myState = STATE_PASSWORD

                elif myState == STATE_PASSWORD:
                    password = sys.stdin.readline()
                    password = password.rstrip()
                    sendToServer('_u<'+myUsername+'>_p<'+password+'>_p2p<'+str(myp2pPort)+'>')
                    myState = STATE_AWAITING_VALIDATION
                else :
                    cmd = sys.stdin.readline()
                    handleClientCmd(cmd)
                    sys.stdout.flush() 

# handles commands sent in from the server
def handleServerCmd(command):

    logging.debug("received server command" + str(command))

    if "<server_broadcast>" in command:
        message = remove_prefix(command,"<server_broadcast>")
        display("[Server]"+str(message))
        return myState

    elif "<online_list>" in command:
        online = remove_prefix(command,"<online_list>")
        onlineList = online.split()
        if online != '':
            for user in onlineList:
                print user
            display('')
        else:
            display('No one else is online right now.')
        return myState

    elif "<login_log>" in command:
        loginLog = remove_prefix(command,"<login_log>")
        loginList = loginLog.split()
        if loginLog != '':
            for user in loginList:
                print user
            display('')
        else:
            display('No users found to have logged in during specified time')
        return myState

    elif "<client_broadcast>" in command:
        message = remove_prefix(command,"<client_broadcast>")
        display("[Broadcast]"+str(message))
        return myState

    elif "<info>" in command:
        message = remove_prefix(command,"<info>")
        display(message)
        return myState

    elif "<message>" in command:
        message = remove_prefix(command,"<message>")
        display(message)
        return myState

    elif "<private_info>" in command:
        command = remove_prefix(command,"<private_info>")
        userIP, userPort, user, myUser = command.split()

        #spawn thread for this p2p connection
        StartThread('p2p_'+user,p2p_connect(userIP, userPort, user, myUser))

        return myState

    # standard server commands
    if "<welcome>" in command:
        display("Welcome to the greatest messaging application ever!")
        command = remove_prefix(command,"<welcome>")
        myUsername = command
        return STATE_AUTHENTICATED
    elif command == "<invalidPass>":
        print "Invalid Password. Please try again"
        return STATE_PASSWORD
    elif command == "<invalidUserPass>":
        print "Invalid Username/Password. Please try again"
        return STATE_USERNAME
    elif command == "<invalid_blocked>":
        print "Invalid Password. Your account has been blocked. Please try again later"
        close_client()
    elif command == "<blocked>":
        print "Your account is blocked due to multiple login failures. Please try again later"
        close_client()
    elif command == "<IP_blocked>":
    	print "Your IP is blocked due to multiple login failures. Please try again later"
        close_client()
    elif command == "<timeout>":
        print("\nYou have been logged out due to inactivity")
        close_client()
    elif command == "<acc_in_use>":
    	print("This account is already logged in.")
    	close_client()

def handleClientCmd(command):
    # remove new line
    cmd = command.strip()

    if cmd == "logout":
        sendToServer('<logout>')
        close_client()
    elif cmd == "whoelse":
        sendToServer('<online_list>')
    elif "whoelsesince " in cmd:
        cmd = remove_prefix(cmd, 'whoelsesince ')
        sendToServer('<login_log>'+cmd)
    elif "broadcast " in cmd:
        cmd = remove_prefix(cmd, 'broadcast ')
        sendToServer('<user_broadcast>'+cmd)
        display('')
    elif "unblock " in cmd:
        cmd = remove_prefix(cmd, 'unblock ')
        sendToServer('<unblock>'+cmd)
    elif "block " in cmd:
        cmd = remove_prefix(cmd, 'block ')
        sendToServer('<block>'+cmd)
    elif "message " in cmd:
        cmd = remove_prefix(cmd, 'message ')
        sendToServer('<message>'+cmd)
        display('')
    elif "startprivate " in cmd:
        cmd = remove_prefix(cmd, 'startprivate ')
        sendToServer('<start_private>'+cmd)
        display('')
    elif "stopprivate " in cmd:
        user = remove_prefix(cmd, 'stopprivate ')
        removeP2PConn(user)
    elif "private " in cmd:
        cmd = remove_prefix(cmd, 'private ')
        cmd = cmd.split()
        recipient = cmd.pop(0)
        message = ' '.join(cmd)
        sendPrivateMessage(recipient, message)
        display('')
    # all other invalid entries
    else:
        display('Error. Invalid command')

# handles commands sent in from connected P2P clients
def handlep2pCommand(clientSocket, command):

	if "<p2p_verification>" in command:
		user = remove_prefix(command,"<p2p_verification>")
		USER_MAP_TO_SOCKET[user] = clientSocket
		SOCKET_MAP_TO_USER[clientSocket] = user
		logging.debug('verified %s for P2P messaging' % user)

	elif "<stop_private>" in command:
		user = SOCKET_MAP_TO_USER[clientSocket]
		USER_MAP_TO_SOCKET.pop(user, None)
		SOCKET_MAP_TO_USER.pop(user, None)		
		logging.debug('removed %s from p2p' % user)

		# remove the socket
		if clientSocket in SOCKET_LIST:
			SOCKET_LIST.remove(clientSocket)
			clientSocket.close()
		

	elif "<private>" in command:
		message = remove_prefix(command,"<private>")
		user = SOCKET_MAP_TO_USER[clientSocket]
		message = str(user) + "(private): " + str(message)
        display(message)

# sends private message to P2P peer
def sendPrivateMessage(user, message):

	logging.debug('sending %s to %s' % (message,user))

	if user in USER_MAP_TO_SOCKET:
		socket = USER_MAP_TO_SOCKET[user]

		try:
			socket.send('<private>'+message)
		except:
			display('User has disconnected')
			removeP2PConn(user)
	else:
		print('Error. Private messaging to %s not enabled' % user)

# sends tag to connected P2P client to close the connection
# removes the connection from dict
def removeP2PConn(user):

	if user in USER_MAP_TO_SOCKET:
		try:
			socket = USER_MAP_TO_SOCKET[user]
			socket.send('<stop_private>')
			USER_MAP_TO_SOCKET.pop(user, None)
			SOCKET_MAP_TO_USER.pop(socket,None)			
			display('Private session with %s ended' % user)
		except:
			pass
	else:
		display('Error. Private messaging to %s not enabled' % user)

#sends to connected server
def sendToServer(command):
    clientSocket.send(command)
    #debug
    logging.debug('sent to server: '+str(command))

#display message client side followed by > on the next line
def display(message):
    if message != '':
        sys.stdout.write(message+'\n')
    sys.stdout.write('>')
    sys.stdout.flush()

#login prompt control
def init_Login(type):

	if type == "user":
		sys.stdout.write('Username:')
		sys.stdout.flush()  
	elif type == "pass":
		sys.stdout.write('Password:')
		sys.stdout.flush()  

# kills client threads and closes P2P sockets
def close_client():
    # stop all threads
    running_threads.clear()

    # kill all p2p connections
    for user in USER_MAP_TO_SOCKET:
    	socket = USER_MAP_TO_SOCKET[user]
    	socket.send('<stop_private>')
    	socket.close()

# helper functions
def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text 


class StoppableThread(threading.Thread):
    """Thread class with a stop() method. The thread itself has to check
    regularly for the stopped() condition."""

    def __init__(self, target):
        super(StoppableThread, self).__init__(target=target)
        self._stop = threading.Event()


def StartThread(name, process):
   """
   Starts a thread and adds an entry to the global dThreads dictionary.
   """
   logging.debug('Starting %s' % name)
   running_threads[process] = StoppableThread(target=process)
   running_threads[process].start()


if __name__ == "__main__":
    StartThread('p2p',p2p_Listener)
    StartThread('main',main_client)