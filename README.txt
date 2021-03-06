Conference

============================================================
Udacity Full Stack Web Developer Nanodegree
============================================================
Project 4

============================================================
Language
============================================================
-Python

============================================================
APIs
============================================================
-Google Cloud Endpoints

============================================================
Sessions and Speakers
============================================================
Sessions and speakers have been implemented.

A sessions contains the properties name,highlights, speakerKey, speakerDisplayName, 
duration, typeOfSession, and startDateTime.
A speaker contains the properties displayName, profileKey, and biography.
============================================================
Wishlist
============================================================
Wishlist was added as the property field "conferenceKeysToAttend" to the profile object.
It can be called by using addSessionTWishlist and getSessionsInWishlist.

============================================================
Additional Queries
============================================================
getLectureSessions and getWorkshopSessions queries have been implemented.

============================================================
Non-Workshop After 7
============================================================
There was an issue where I could only use 1 inequality filter in my query.
This was resolved by querying for only startDate then using a for loop to remove workshops.

============================================================
Instructions
===========================================================
-Update the value of application in app.yaml to the app ID registered in the App Engine admin console 

-Update the values in settings.py with new app ID

-Update the value of CLIENT_ID in static/js/app.js to the Web client ID

-Mark the configuration files as unchanged with
$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js

-Run the app with the devserver using dev_appserver.py DIR

-Access from a webbrowser at http://localhost:8080