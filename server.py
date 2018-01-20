#! /usr/bin/python

# Written by Michael for COMP3331 assignment 1
# server.py

import sys
import select
import re
import logging
import time

from socket import *

if(len(sys.argv) < 4):
    print 'Usage : python server.py serverPort blockDuration timeout'
    sys.exit()

# debug
if (len(sys.argv) > 4) and sys.argv[4] == '-d':
    logging.basicConfig(level=logging.DEBUG)

# Server Configurations
server_port = int(sys.argv[1])
block_duration = int(sys.argv[2])
timeout = int(sys.argv[3])
RECV_BUFFER = 4096
cred_fname = 'credentials.txt'
incorrect_login_block = 3 # tries

# List/dicionaries
SOCKET_LIST = []
SOCKET_MAP_TO_USER = {}
SOCKET_MAP_TO_IP = {}
SOCKET_STATE = {}
USER_MAP_TO_SOCKET = {}
CREDENTIALS = {}
INCORRECT_LOGIN = {}
LOGIN_BLOCK = {}
LOGIN_LOG = {}
LAST_HEARD = {}
BLOCK_LIST = {}
OFFLINE_MESSAGES = {}
P2P_PORT = {}

# User states
S_NOLOGIN = 1
S_ONLINE = 2

# time function - this returns rounded time in seconds since 1 Jan 1970
getTime = lambda: int(round(time.time()))

def run_server():

    # setup socket
    serverSocket = socket(AF_INET, SOCK_STREAM)
    serverSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    serverSocket.bind(('', server_port))
    serverSocket.listen(10)

    # add server socket object to the list of readable connections
    SOCKET_LIST.append(serverSocket)

    logging.debug("Server started on port " + str(server_port))

    while 1:

        ready_to_read,ready_to_write,in_error = select.select(SOCKET_LIST,[],[],0)

        for sock in ready_to_read:
            # a new connection request received
            if sock == serverSocket: 
                sockfd, addr = serverSocket.accept()
                SOCKET_LIST.append(sockfd)
                SOCKET_MAP_TO_IP[sockfd] = addr[0]
                logging.debug('Client (%s, %s) connected, socket' % addr)
                logging.debug('Socket' + str(sockfd))

                # Assign default states for user
                SOCKET_STATE[sockfd] = S_NOLOGIN
                INCORRECT_LOGIN[sockfd] = 0

            # a message from a client, not a new connection
            else:
                # process data recieved from client, 
                try:
                    # receiving data from the socket.
                    data = sock.recv(RECV_BUFFER)
                    if data:
                        logging.debug('Received ' + data + ' from' + str(sock.getpeername()))
                        handleClientCommand(sock,data)               
                    else:
                        # remove the socket that's broken    
                        if sock in SOCKET_LIST:
                            SOCKET_LIST.remove(sock)

                        # at this stage, no data means probably the connection has been broken
                        # client might be offline
                        logging.debug(str(sock.getpeername())+' closed the connection.')
                # exception 
                except:
                    continue

        # manage timeouts
        handleTimeout()

    serverSocket.close()

# watchout for idle clients
def handleTimeout():
    currentTime = getTime()

    #copy our last_heard dict as we might be logging users out
    CHECK_LAST_HEARD = LAST_HEARD.copy()

    for userSocket in CHECK_LAST_HEARD:
        if (currentTime - LAST_HEARD[userSocket]) >= timeout:
            logging.debug('timing out %s for inactivity' % SOCKET_MAP_TO_USER[userSocket])
            userSocket.send('<timeout>')
            logUserOut(userSocket)
            
    CHECK_LAST_HEARD = CHECK_LAST_HEARD.clear()

# handles commands sent in by connected clients
def handleClientCommand(clientSocket, command):
    logging.debug('handling command '+ command + ' from ' + str(clientSocket))

    currentTime = getTime()
    clientIP = SOCKET_MAP_TO_IP[clientSocket]

    # check if IP is blocked
    if isBlocked(clientIP):
        # check if we can unblock the dude 
        if not blockOver(clientIP):
            clientSocket.send('<IP_blocked>')
            logging.debug('sent <IP_blocked> to client')
            return

    # handle logins
    if SOCKET_STATE[clientSocket] < S_ONLINE:
        handleClientLogin(clientSocket, command)
        return

    # handle all other client commands

    # logout
    if command == "<logout>":
        logUserOut(clientSocket)
        return

    # whoelse
    if command == "<online_list>":
        response = '<online_list>'
        for userSocket in LAST_HEARD:
            if userSocket == clientSocket: continue
            response = response + SOCKET_MAP_TO_USER[userSocket] + ' '
        clientSocket.send(response)
        logging.debug('sent to client:'+ str(response))

    # whoelsesince
    if "<login_log>" in command:
        time = int(remove_prefix(command,'<login_log>'))
        time = currentTime - time
        response = '<login_log>' 

        for user in LOGIN_LOG:
            if user == SOCKET_MAP_TO_USER[clientSocket]: continue
            if LOGIN_LOG[user] > time:
                response = response + user + ' '
        clientSocket.send(response)
        logging.debug('sent to client:'+ str(response))

    # broadcast
    if "<user_broadcast>" in command:
        message = remove_prefix(command, '<user_broadcast>')
        message = str(SOCKET_MAP_TO_USER[clientSocket]) + ':' + message
        excludedClients = [clientSocket]
        
        if hasBlockers(excludedClients, clientSocket):
            response = '<info>Message could not be delivered to some recipients'
            clientSocket.send(response)
        broadcast(excludedClients, message, "client")

    # block
    if "<block>" in command:

        clientUsername = SOCKET_MAP_TO_USER[clientSocket]
        user = remove_prefix(command, '<block>')
        response = '<info>'

        # not sure if set() worked correctly in login, just in case we do 
        # set declaration via exception
        if user in CREDENTIALS and user != clientUsername:
            try:
                BLOCK_LIST[clientUsername].add(user)
            except KeyError:
                BLOCK_LIST[clientUsername] = {user}


            response = response + str(user) + " is blocked"
        elif user == clientUsername:
            response = response + "Error. Cannot block self"
        else:
            response = response + "Invalid user"

        clientSocket.send(response)
        logging.debug('sent to client:'+ str(response))

    # unblock
    if "<unblock>" in command:
        clientUsername = SOCKET_MAP_TO_USER[clientSocket]
        user = remove_prefix(command, '<unblock>')
        response = '<info>'

        if user in BLOCK_LIST[clientUsername]:
            BLOCK_LIST[clientUsername].remove(user)
            response = response + str(user) + " is unblocked"
        elif user == clientUsername:
            response = response + "You can't block/unblock yourself"
        else:
            response = response + "Error. "+ str(user) + " was not blocked"

        clientSocket.send(response)
        logging.debug('sent to client:'+ str(response))

    # message
    if "<message>" in command:
        clientUsername = SOCKET_MAP_TO_USER[clientSocket]
        command = remove_prefix(command, '<message>')
        command = command.split()
        recipient = command.pop(0)
        message = ' '.join(command)
        response = '<info>'

        if recipient == clientUsername:
            response = response + "Error. You can't message yourself"
            clientSocket.send(response)
        elif recipient not in CREDENTIALS:
            response = response + "Error. Invalid user"
            clientSocket.send(response)
        elif clientUsername not in BLOCK_LIST[recipient]:
            # deliver message
            # check if user is online
            if recipient in USER_MAP_TO_SOCKET:
                recipientSocket = USER_MAP_TO_SOCKET[recipient]
                recipientSocket.send('<message>'+str(clientUsername)+': '+str(message))
            else:
                # leave him an offline message
                OFFLINE_MESSAGES[recipient].append('<message>'+str(clientUsername)+': '+str(message))
        else:
            response = response + "Your message could not be delivered as the recipient has blocked you"
            clientSocket.send(response)
            logging.debug('sent to client:'+ str(response))

    #P2P
    if "<start_private>" in command:
        recipient = remove_prefix(command, '<start_private>')
        clientUsername = SOCKET_MAP_TO_USER[clientSocket]

        if recipient == clientUsername:
            response = "<info>Error. You can't start a private session with yourself"
            clientSocket.send(response)

        elif recipient not in CREDENTIALS:
            response = "<info>Error. Invalid user"
            clientSocket.send(response)
        elif clientUsername not in BLOCK_LIST[recipient]:
            # deliver message
            # check if user is online
            if recipient in USER_MAP_TO_SOCKET:
                recipientSocket = USER_MAP_TO_SOCKET[recipient]
                recipientIP = SOCKET_MAP_TO_IP[recipientSocket]
                recipientPort = P2P_PORT[recipient]
                clientSocket.send('<private_info>'+str(recipientIP)+' '+str(recipientPort)+' '+str(recipient)+' '+str(clientUsername))
                logging.debug('sent to client:'+'<private_info>'+str(recipientIP)+' '+str(recipientPort)+' '+str(recipient)+' '+str(clientUsername))
            else:
                response = "<info>User is offline"
                clientSocket.send(response)
                logging.debug('sent to client:'+ str(response))
        else:
            response = "<info>You have been blocked by that user"
            clientSocket.send(response)
            logging.debug('sent to client:'+ str(response))


    # update last heard for client
    heardFrom(clientSocket,currentTime)

# NOTE: only checks for online users
# adds them into excludedClients
def hasBlockers(excludedClients, clientSocket):

    user = SOCKET_MAP_TO_USER[clientSocket]
    result = False

    for online_userSocket in LAST_HEARD:
        online_user = SOCKET_MAP_TO_USER[online_userSocket]
        if user == online_user: continue
        if user in BLOCK_LIST[online_user]:
            excludedClients.append(USER_MAP_TO_SOCKET[online_user])
            result = True

    return result

# retrieves credentials from file and puts into a a dict for quick access
def retrieveCredentials():
    creds = []
    with open(cred_fname) as f:
        creds = f.readlines()
    
    # remove new lines
    creds = [x.strip() for x in creds]

    # hash all the usernames and passwords
    for entry in creds:
        username,password = entry.split()
        CREDENTIALS[username] = password  
        # setup offline messages and block list for users  
        OFFLINE_MESSAGES[username] = []
        BLOCK_LIST[username] = set()
    logging.debug('Loaded Credential File')

# handles login attemptes from clients
def handleClientLogin(clientSocket, entry):

    currentTime = getTime()

    #penis
    # format given by official client is
    # _u<username>_p<password>
    match = re.match(r'_u<(.*)>_p<(.*)>_p2p<(.*)>', entry)
    if match:
        user = match.group(1)
        pwd = match.group(2)
        p2p = match.group(3)

        # check if user account is being blocked
        if isBlocked(user) and not blockOver(user):
            clientSocket.send('<blocked>')
            return

        if user in CREDENTIALS and pwd == CREDENTIALS[user]:

            # check if the account is already being logged in first
            if isOnline(user):
                clientSocket.send('<acc_in_use>')
                return

            # user authenticated
            logUserIn(clientSocket, user)
            P2P_PORT[user] = p2p
            excludedClients = [clientSocket]
            broadcast(excludedClients, user+' has logged in.', "server")

            # check if there's any offline messages for him
            while len(OFFLINE_MESSAGES[user]) > 0: 
                msg = OFFLINE_MESSAGES[user].pop(0)
                clientSocket.send(msg)

        elif user in CREDENTIALS: #correct username wrong password

            INCORRECT_LOGIN[clientSocket]+= 1
            if INCORRECT_LOGIN[clientSocket] == incorrect_login_block:
                clientSocket.send('<invalid_blocked>')
                # reset login warning and block user IP
                INCORRECT_LOGIN[clientSocket] = 0

                # simple check to see if it's an invalid username
                if user not in CREDENTIALS:
                    blockConn(SOCKET_MAP_TO_IP[clientSocket])
                else:
                    blockConn(user)
            else :
                clientSocket.send('<invalidPass>')

        else : #invalid username
            INCORRECT_LOGIN[clientSocket]+= 1
            if INCORRECT_LOGIN[clientSocket] == incorrect_login_block:
                clientSocket.send('<invalid_blocked>')

                # reset login warning and block user IP
                INCORRECT_LOGIN[clientSocket] = 0
                blockConn(SOCKET_MAP_TO_IP[clientSocket])

            else :
                clientSocket.send('<invalidUserPass>')

#block connection from client by adding it into LOGIN_BLOCK dict      
def blockConn(client):
    currentTime = getTime()
    LOGIN_BLOCK[client] = currentTime
    logging.debug('Blocked '+ str(client))

#checks if a user is online
def isOnline(user):
    for userSockets in LAST_HEARD:
        username = SOCKET_MAP_TO_USER[userSockets]
        if user == username:
            return True

    return False

#updates the LAST_HEARD dict (used when client sends in commands)
def heardFrom(clientSocket, currentTime):
    LAST_HEARD[clientSocket] = currentTime

#check if client is currently under the server block list
def isBlocked(client):
    if client in LOGIN_BLOCK:
        return True
    else:
        return False

#checks if client's block is over
def blockOver(client):
    currentTime = getTime()

    # check if block is over, if it is, unblock and return true
    if (currentTime - LOGIN_BLOCK[client]) > block_duration:
        LOGIN_BLOCK.pop(client, None)
        return True
    else:
        return False

# sets states for user after authentication
def logUserIn(clientSocket, user):  
    
    currentTime = getTime()

    # setup states
    SOCKET_STATE[clientSocket] = S_ONLINE
    SOCKET_MAP_TO_USER[clientSocket] = user
    USER_MAP_TO_SOCKET[user] = clientSocket
    LOGIN_LOG[user] = currentTime
    LAST_HEARD[clientSocket] = currentTime 

    # send authentication acknowledgement to client
    clientSocket.send('<welcome>'+str(user))
    return

#reset and removes states of users (this does not remove the login logs)
def logUserOut(clientSocket):

    user = SOCKET_MAP_TO_USER[clientSocket]
    SOCKET_MAP_TO_IP.pop(clientSocket, None)
    SOCKET_MAP_TO_USER.pop(clientSocket, None)
    SOCKET_STATE.pop(clientSocket, None)
    USER_MAP_TO_SOCKET.pop(user, None)
    LAST_HEARD.pop(clientSocket, None)

    # if our server loop hasn't removed the socket, remove it
    if clientSocket in SOCKET_LIST:
        SOCKET_LIST.remove(clientSocket)

    # close connection
    clientSocket.close()

    # tell everyone
    excludedClients = []
    broadcast(excludedClients, user+' has logged out.', "server")
    logging.debug('broadcasting %s has logged out' % user)

# broadcast chat messages to all online clients except excludedClients
def broadcast(excludedClients, message, type):
    for clientSocket in LAST_HEARD:
        if clientSocket in excludedClients:
            continue

        try :
            if type == "server":
                clientSocket.send('<server_broadcast>'+message)
            elif type == "client":
                clientSocket.send('<client_broadcast>'+message)
        except :
            # broken socket connection
            socket.close()
            # broken socket, remove it
            if socket in SOCKET_LIST:
                SOCKET_LIST.remove(socket)

# helper functions
def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text 

if __name__ == "__main__":
    retrieveCredentials()
    sys.exit(run_server())
    
#ilovemen



