#!/usr/bin/env python
from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session, SessionForm, SessionForms, SessionTypes
from models import Speaker, SpeakerForm, SpeakerForms

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',   
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1, required=True),
    typeOfSession=messages.StringField(2)
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSIONS_BY_SPEAKER = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speakerKey=messages.StringField(1),
)

SESSIONS_BY_TYPE = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    type=messages.StringField(2),
)

SESSION_WISH_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

SPEAKER_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1, required=True),
)

WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1, required=True),
)

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')
        for field in request.all_fields():
            data = getattr(request, field.name)
            if data not in (None, []):
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)


    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )


    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)
        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None
        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}
            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")
            if filtr["operator"] != "=":
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]
            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')

    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions',
            http_method='GET', name='getConferenceSessions')
    
    def getConferenceSessions(self, request):
        """Given a conference, returns all sessions."""
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        sessions = Session.query(ancestor=ndb.Key(Conference, conf.key.id()))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
            path='conference/{websafeConferenceKey}/sessions/by_type/{typeOfSession}',
            http_method='GET', name='getConferenceSessionsByType')
    
    def getConferenceSessionsByType(self, request):
        """Given a conference, return all sessions of a specified type"""
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        typeOfSession = str(data['typeOfSession'])
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        sessions = Session.query(Session.typeOfSession == typeOfSession, ancestor=ndb.Key(Conference, conf.key.id()))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - Session objects - - - - - - - - - - - - - - - - - - -

    def _createSessionObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = _getUserId(user)
        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can add sessions.')
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        if data['date']:
            data['date'] = datetime.strptime(data['date'][:10], "%Y-%m-%d").date()
        if data['startTime']:
            data['startTime'] = datetime.strptime(data['startTime'][:5], "%H:%M").time()
        p_key = ndb.Key(Conference, conf.key.id())
        c_id = Session.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Session, c_id, parent=p_key)
        data['key'] = c_key
        del data['websafeConferenceKey']
        del data['websafeKey']
        Session(**data).put()
        sessions = Session.query(Session.speaker == data['speakerDisplayName'],
            ancestor=p_key)
        if len(list(sessions)) > 1:
            cache_data = {}
            cache_data['speakerDisplayName'] = data['speakerDisplayName']
            cache_data['sessionNames'] = [session.name for session in sessions]
            if not memcache.set('featured_speaker', cache_data):
                logging.error('Memcache set failed.')
        return self._copySessionToForm(request)

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            if hasattr(session, field.name):
                if field.name in ['startTime', 'date']:
                    setattr(sf, field.name, str(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
            elif field.name == "websafeKey":
                setattr(sf, field.name, session.key.urlsafe())
        sf.check_initialized()
        return sf

    @endpoints.method(SESSION_POST_REQUEST, SessionForm,
            path='sessions/{websafeConferenceKey}',
            http_method='POST', name='createSession')
    
    def createSession(self, request):
        """Open to the organizer of the conference"""
        return self._createSessionObject(request)

    @endpoints.method(SPEAKER_GET_REQUEST, SessionForms,
            path='sessions/{speaker}',
            http_method='GET', name='getSessionsBySpeaker')
    
    def getSessionsBySpeaker(self, request):
        """Given a speaker, return all sessions given by him/her across all conferences"""
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        speaker = data['speaker']
        sessions = Session.query(Session.speaker == speaker)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            http_method='GET', name='getEarlyNonWorkshopSessions')
    
    def getEarlyNonWorkshopSessions(self, request):
        """Returns non-workshop sessions occurring before 7pm"""
        sessions = Session.query(ndb.AND(
                Session.startTime != None,
                Session.startTime <= timed(hour=19)
                ))
        filtered_sessions = []
        for session in sessions:
            if 'workshop' in session.typeOfSession:
                continue
            else:
                filtered_sessions.append(session)
        return SessionForms(
            items=[self._copySessionToForm(session) for session in filtered_sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            http_method='GET', name='getWorkshopSessions')
    
    def getWorkshopSessions(self, request):
        """Returns workshop sessions """
        sessions = Session.query(ndb.AND(
                Session.typeOfSession == 'WORKSHOP'
                ))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SessionForms,
            http_method='GET', name='getLectureSessions')
    
    def getLectureSessions(self, request):
        """Returns lecture sessions"""
        sessions = Session.query(ndb.AND(
                Session.typeOfSession == 'LECTURE'
                ))
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

    @endpoints.method(message_types.VoidMessage, SpeakerForm,
            http_method='GET', name='getFeaturedSpeaker')
    
    def getFeaturedSpeaker(self, request):
        """Returns the sessions of the featured speaker"""
        data = memcache.get('featured_speaker')
        from pprint import pprint
        pprint(data)
        sessions = []
        sessionNames = []
        speaker = None
        if data and data.has_key('speaker') and data.has_key('sessionNames'):
            speaker = data['speaker']
            sessionNames = data['sessionNames']
        else:
            upcoming_session = Session.query(Session.date >= datetime.now())\
                                    .order(Session.date, Session.startTime).get()
            if upcoming_session:
                speaker = upcoming_session.speaker
                sessions = Session.query(Session.speaker == speaker)
                sessionNames = [session.name for session in sessions]
        sf = SpeakerForm()
        for field in sf.all_fields():
            if field.name == 'sessionNames':
                setattr(sf, field.name, sessionNames)
            elif field.name == 'speaker':
                setattr(sf, field.name, speaker)
        sf.check_initialized()
        return sf


# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()
        return profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        prof = self._getProfileFromUser()
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        prof.put()
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

    @endpoints.method(WISHLIST_POST_REQUEST, SessionForm,
            http_method='POST', name='addSessionToWishlist')
    
    def addSessionToWishlist(self, request):
        """Saves a session to a user's wishlist"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        session = ndb.Key(urlsafe=request.websafeSessionKey).get()
        if not session:
            raise endpoints.NotFoundException(
                'No session found with key: %s' % request.websafeSessionKey)
        prof = self._getProfileFromUser()
        if session.key in prof.sessionsToAttend:
            raise endpoints.BadRequestException(
                'Session already saved to wishlist: %s' % request.websafeSessionKey)
        prof.sessionsToAttend.append(session.key)
        prof.put()
        return self._copySessionToForm(session)

    @endpoints.method(message_types.VoidMessage, SessionForms,
            http_method='POST', name='getSessionsInWishlist')
    
    def getSessionsInWishlist(self, request):
        """Returns a user's wishlist of sessions"""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        prof = self._getProfileFromUser()
        session_keys = prof.sessionsToAttend
        sessions = [session_key.get() for session_key in session_keys]
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])
        if confs:
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)
        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/put',
            http_method='GET', name='putAnnouncement')

    def putAnnouncement(self, request):
        """Put Announcement into memcache"""
        return StringMessage(data=self._cacheAnnouncement())

# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser()
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)
        if reg:
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True
        else:
            if wsck in prof.conferenceKeysToAttend:
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser()
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )

    


api = endpoints.api_server([ConferenceApi])
