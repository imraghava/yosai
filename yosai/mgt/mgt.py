"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

from cryptography.fernet import Fernet
from abc import ABCMeta, abstractmethod
import copy

from yosai import(
    AuthenticationException,
    DefaultAuthenticator,
    DisabledCacheManager,
    DefaultMGTSettings,
    DefaultSessionManager,
    DefaultSessionContext,
    DefaultSessionKey,
    DefaultSubjectContext,
    DefaultEventBus,
    IllegalArgumentException,
    InvalidSessionException,
    LogManager,
    ModularRealmAuthorizer,
    DeleteSubjectException,
    SaveSubjectException,
    SerializationManager,
    UnavailableSecurityManagerException,
    UnrecognizedAttributeException,
    mgt_abcs,
    authc_abcs,
    event_abcs,
    cache_abcs,
)


class AbstractRememberMeManager(mgt_abcs.RememberMeManager):
    """
    Abstract implementation of the RememberMeManager interface that handles
    serialization and encryption of the remembered user identity.

    The remembered identity storage location and details are left to
    subclasses.

    Default encryption key
    -----------------------
    This implementation uses the Fernet API from PyCA's cryptography for
    symmetric encryption. As per the documentation, Fernet uses AES in CBC mode
    with a 128-bit key for encryption and uses PKCS7 padding:
        https://cryptography.io/en/stable/fernet/

    It also uses a default, generated symmetric key to both encrypt and decrypt
    data.  As AES is a symmetric cipher, the same key is used to both encrypt
    and decrypt data, BUT NOTE:

    Because Yosai is an open-source project, if anyone knew that you were
    using Yosai's default key, they could download/view the source, and with
    enough effort, reconstruct the key and decode encrypted data at will.

    Of course, this key is only really used to encrypt the remembered
    IdentifierCollection, which is typically a user id or username.  So if you
    do not consider that sensitive information, and you think the default key
    still makes things 'sufficiently difficult', then you can ignore this
    issue.

    However, if you do feel this constitutes sensitive information, it is
    recommended that you provide your own key and set it via the cipher_key
    property attribute to a key known only to your application,
    guaranteeing that no third party can decrypt your data.

    You can generate your own key by importing fernet and calling its
    generate_key method:
       >>> from cryptography.fernet import Fernet
       >>> key = Fernet.generate_key()

    your key will be a byte string that looks like this:
        b'cghiiLzTI6CUFCO5Hhh-5RVKzHTQFZM2QSZxxgaC6Wo='

        copy and paste YOUR newly generated byte string, excluding the
        bytestring notation, into its respective place in /conf/yosai_settings.json
        following this format:
            DEFAULT_CIPHER_KEY = "cghiiLzTI6CUFCO5Hhh-5RVKzHTQFZM2QSZxxgaC6Wo="
    """

    def __init__(self):

        # new to yosai:
        self.serialization_manager = SerializationManager()

        self.encryption_cipher_key = None
        self.decryption_cipher_key = None

        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # !!!
        # !!!                    HEY  YOU!
        # !!! Generate your own key using the instructions above and update
        # !!! your config file to include it.  The code below references it.
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        self.set_cipher_key(DefaultMGTSettings.default_cipher_key)

    def set_cipher_key(self, cipher_key):
        """
        :param cipher_key: the private key used to encrypt and decrypt
        :type cipher_key: a string
        """
        cipher_key = bytes(cipher_key, 'utf-8')
        self.encryption_cipher_key = cipher_key
        self.decryption_cipher_key = cipher_key

    @abstractmethod
    def forget_identity(self, subject):
        """
        Forgets (removes) any remembered identity data for the specified
        Subject instance.

        :param subject: the subject instance for which identity data should be
                        forgotten from the underlying persistence mechanism
        """
        pass

    def is_remember_me(self, authc_token):
        """
        Determines whether remember me services should be performed for the
        specified token.  This method returns True iff:

        - The authc_token is not None and
        - The authc_token is an instance of RememberMeAuthenticationToken and
        - authc_token.is_remember_me is True

        :param authc_token: the authentication token submitted during the
                            successful authentication attempt
        :returns: True if remember me services should be performed as a
                  result of the successful authentication attempt
        """

        return ((authc_token is not None) and
                (isinstance(authc_token,
                            authc_abcs.RememberMeAuthenticationToken)) and
                (authc_token.is_remember_me))

    def on_successful_login(self, subject, authc_token, account):
        """
        Reacts to the successful login attempt by first always
        forgetting any previously stored identity.  Then if the authc_token
        is a RememberMe type of token, the associated identity
        will be remembered for later retrieval during a new user session.

        :param subject: the subject whose identifying attributes are being
                        remembered
        :param authc_token:  the token that resulted in a successful
                             authentication attempt
        :param account: account that contains the authentication info resulting
                        from the successful authentication attempt
        """
        # always clear any previous identity:
        self.forget_identity(subject)

        # now save the new identity:
        if (self.is_remember_me(authc_token)):
            self.remember_identity(subject, authc_token, account)
        else:
            msg = ("AuthenticationToken did not indicate that RememberMe is "
                   "requested.  RememberMe functionality will not be executed "
                   "for corresponding account.")
            print(msg)
            # log debug here

    # yosai omits authc_token argument as its for an edge case
    def remember_identity(self, subject, identifiers=None, account=None):
        """
        Yosai consolidates rememberIdentity, an overloaded method in java,
        to a method that will use an identifiers-else-account logic.

        Remembers a subject-unique identity for retrieval later.  This
        implementation first resolves the exact identifying attributes to
        remember.  It then remembers these identifying attributes by calling
            remember_identity(Subject, IdentifierCollection)

        :param subject:  the subject for which the identifying attributes are
                         being remembered
        :param identifiers: the identifying attributes to remember for retrieval
                            later on
        :param account: the account containing authentication info resulting
                         from the successful authentication attempt
        """
        if not identifiers:  # then account must not be None
            try:
                identifiers = self.get_identity_to_remember(subject, account)
            except AttributeError:
                msg = "Neither account nor identifiers arguments passed"
                raise IllegalArgumentException(msg)

        serialized = self.convert_identifiers_to_bytes(identifiers)
        self.remember_serialized_identity(subject, serialized)

    def convert_identifiers_to_bytes(self, identifiers):
        """
        Encryption requires a binary type as input, so this method converts
        the identifiers collection object to one.

        :type identifiers: a serializable IdentifierCollection object
        :returns: a bytestring
        """
        # convert to bytes in case serialization doesn't do so:
        return bytes(self.serialization_manager.serialize(identifiers))

    @abstractmethod
    def remember_serialized_identity(subject, serialized):
        """
        Persists the identity bytes to a persistent store for retrieval
        later via the get_remembered_serialized_identity(SubjectContext)
        method.

        :param subject: the Subject for whom the identity is being serialized
        :param serialized: the serialized bytes to be persisted.
        """
        pass

    def get_remembered_identifiers(self, subject_context):
        identifiers = None
        try:
            serialized = self.get_remembered_serialized_identity(subject_context)

            if serialized:
                identifiers = self.convert_bytes_to_identifiers(identifiers,
                                                                subject_context)
        except Exception as ex:
            identifiers = \
                self.on_remembered_identifier_failure(ex, subject_context)
        return identifiers

    @abstractmethod
    def get_remembered_serialized_identity(subject_context):
        """
        Based on the given subject context data, retrieves the previously
        persisted serialized identity, or None if there is no available data.
        The context map is usually populated by a SubjectBuilder
        implementation.  See the SubjectFactory class constants for Yosai's
        known map keys.

        :param subject_context: the contextual data, usually provided by a
                                SubjectBuilder implementation, that
                                is being used to construct a Subject instance.

        :returns: the previously persisted serialized identity, or None if
                  no such data can be acquired for the Subject
        """
        pass

    def convert_bytes_to_identifiers(self, serialized, subject_context):
        """
        If a cipher_service is available, it will be used to first decrypt the
        serialized message.  Then, the bytes are deserialized and returned.

        :param serialized:      the bytes to decrypt if necessary and then
                                deserialize
        :param subject_context: the contextual data, usually provided by a
                                SubjectBuilder implementation, that is being
                                used to construct a Subject instance
        :returns: the de-serialized and possibly decrypted identifiers
        """
        # if may not be decrypted, so try but if fails continue
        try:
            serialized = self.decrypt(serialized)
        except:
            pass

        return self.serialization_manager.deserialize(serialized)

    def on_remembered_principal_failure(self, exc, subject_context):
        """
        Called when an exception is thrown while trying to retrieve principals.
        The default implementation logs a debug message and forgets ('unremembers')
        the problem identity by calling forget_identity(subject_context) and
        then immediately re-raises the exception to allow the calling
        component to react accordingly.

        This method implementation never returns an object - it always rethrows,
        but can be overridden by subclasses for custom handling behavior.

        This most commonly would be called when an encryption key is updated
        and old identifiers are retrieved that have been encrypted with the
        previous key.

        :param exc: the exception that was thrown
        :param subject_context: the contextual data, usually provided by a
                                SubjectBuilder implementation, that is being
                                used to construct a Subject instance
        :raises:  the original Exception passed is propagated in all cases
        """
        msg = ("There was a failure while trying to retrieve remembered "
               "principals.  This could be due to a configuration problem or "
               "corrupted principals.  This could also be due to a recently "
               "changed encryption key.  The remembered identity will be "
               "forgotten and not used for this request.", exc)
        print(msg)
        # log debug here

        self.forget_identity(subject_context)

        # propagate - security manager implementation will handle and warn
        # appropriately:
        raise exc

    def encrypt(self, serialized):
        """
        Encrypts the serialized message using Fernet

        :param serialized: the serialized object to encrypt
        :type serialized: bytes
        :returns: an encrypted bytes returned by Fernet
        """

        fernet = Fernet(self.encryption_cipher_key)
        return fernet.encrypt(serialized)

    def decrypt(self, encrypted):
        """
        decrypts the encrypted message using Fernet

        :param encrypted: the encrypted message
        :returns: the decrypted, serialized identifiers collection
        """
        fernet = Fernet(self.decryption_cipher_key)
        return fernet.decrypt(encrypted)

    def on_failed_login(self, subject, authc_token, ae):
        """
        Reacts to a failed login by immediately forgetting any previously
        remembered identity.  This is an additional security feature to prevent
        any remenant identity data from being retained in case the
        authentication attempt is not being executed by the expected user.

        :param subject: the subject which executed the failed login attempt
        :param authc_token:   the authentication token resulting in a failed
                              login attempt - ignored by this implementation
        :param ae:  the exception thrown as a result of the failed login
                    attempt - ignored by this implementation
        """
        self.forget_identity(subject)

    def on_logout(self, subject):
        """
        Reacts to a subject logging out of the application and immediately
        forgets any previously stored identity and returns.

        :param subject: the subject logging out
        """
        self.forget_identity(subject)


# also known as ApplicationSecurityManager in Shiro 2.0 alpha:
class DefaultSecurityManager(mgt_abcs.SecurityManager,
                             event_abcs.EventBusAware,
                             cache_abcs.CacheManagerAware):

    def __init__(self, securityutils):
        self.security_utils = securityutils
        self.realms = None
        self._event_bus = DefaultEventBus()
        self._cache_manager = DisabledCacheManager()  # cannot be set to None

        # new to Yosai is the injection of the eventbus:
        self.authenticator = DefaultAuthenticator(self._event_bus)

        # TBD:  add support for eventbus to the authorizer and inject the bus:
        self.authorizer = ModularRealmAuthorizer()

        self.session_manager = None
        self.remember_me_manager = None
        self.subject_store = None
        self.subject_factory = None

    """
    * ===================================================================== *
    * Getters and Setters                                                   *
    * ===================================================================== *
    """
    @property
    def authenticator(self):
        return self._authenticator

    @authenticator.setter
    def authenticator(self, authenticator):
        if authenticator:
            self._authenticator = authenticator

            if (isinstance(self.authenticator, DefaultAuthenticator)):
                self.authenticator.realms = self.realms

            self.apply_event_bus(self.authenticator)
            self.apply_cache_manager(self.authenticator)

        else:
            msg = "authenticator parameter must have a value"
            raise IllegalArgumentException(msg)

    @property
    def authorizer(self):
        return self._authorizer

    @authorizer.setter
    def authorizer(self, authorizer):
        if authorizer:
            self._authorizer = authorizer
            self.apply_event_bus(self.authorizer)
            self.apply_cache_manager(self.authorizer)
        else:
            msg = "authorizer parameter must have a value"
            raise IllegalArgumentException(msg)

    @property
    def cache_manager(self):
        return self._cache_manager

    @cache_manager.setter
    def cache_manager(self, cachemanager):
        if (cachemanager):
            self._cache_manager = cachemanager
            self.apply_cache_manager(
                self.get_dependencies_for_injection(self._cache_manager))

        else:
            msg = ('Incorrect parameter.  If you want to disable caching, '
                   'configure a disabled cachemanager instance')
            raise IllegalArgumentException(msg)

    #  property required by EventBusAware interface:
    @property
    def event_bus(self):
        return self._event_bus

    @event_bus.setter
    def event_bus(self, eventbus):
        if eventbus:
            self._event_bus = eventbus
            self.apply_event_bus(
                self.get_dependencies_for_injection(self._event_bus))

        else:
            msg = 'eventbus parameter must have a value'
            raise IllegalArgumentException(msg)

    def set_realms(self, realm_s):
        """
        :realm_s: an immutable collection of one or more realms
        :type realm_s: tuple
        """
        if realm_s:
            self.apply_event_bus(realm_s)
            self.apply_cache_manager(realm_s)

            authc = self.authenticator
            if (isinstance(authc, DefaultAuthenticator)):
                authc.realms = realm_s

            authz = self.authorizer
            if (isinstance(authz, ModularRealmAuthorizer)):
                authz.realms = realm_s

        else:
            msg = 'Cannot pass None as a parameter value for realms'
            raise IllegalArgumentException(msg)

    # new to yosai, helper method:
    def apply_target_s(self, validate_apply, target_s):
        try:
            for target in target_s:
                validate_apply(target)
        except TypeError:
            validate_apply(target_s)

    def apply_cache_manager(self, target_s):
        """
        :param target: the object or objects that, if eligible, are to have
                       the cache manager set
        :type target: an individual object instance or iterable
        """
        # yosai refactored, deferring iteration to the methods that call it
        def validate_apply(target):
            if isinstance(target, cache_abcs.CacheManagerAware):
                target.cache_manager = self.cache_manager

        self.apply_target_s(validate_apply, target_s)

    def apply_event_bus(self, target_s):
        """
        :param target: the object or objects that, if eligible, are to have
                       the eventbus set
        :type target: an individual object instance or iterable
        """
        # yosai refactored, deferring iteration to the methods that call it

        def validate_apply(target):
            if isinstance(target, event_abcs.EventBusAware):
                target.event_bus = self.event_bus

        self.apply_target_s(validate_apply, target_s)

    def get_dependencies_for_injection(self, ignore):
        deps = {self._event_bus, self._cache_manager, self.realms,
                self.authenticator, self.authorizer,
                self.session_manager, self.subject_store,
                self.subject_factory}
        try:
            deps.remove(ignore)
        except KeyError:
            msg = ("Could not remove " + str(ignore) +
                   " from dependencies_for_injection: ")
            print(msg)
            # log warning here

        return deps

    """
    * ===================================================================== *
    * Authenticator Methods                                                 *
    * ===================================================================== *
    """

    def authenticate_account(self, authc_token):
        return self.authenticator.authenticate_account(authc_token)

    """
    * ===================================================================== *
    * Authorizer Methods                                                    *
    *
    * Note: Yosai refactored authz functionality in order to eliminate
    *       method overloading
    * ===================================================================== *
    """
    def is_permitted(self, identifiers, permission_s):
        """
        :param identifiers: a collection of identifiers
        :type identifiers: Set

        :param permission_s: a collection of 1..N permissions
        :type permission_s: List of Permission object(s) or String(s)

        :returns: a List of tuple(s), containing the Permission and a Boolean
                  indicating whether the permission is granted
        """
        return self.authorizer.is_permitted(identifiers, permission_s)

    def is_permitted_all(self, identifiers, permission_s):
        """
        :param identifiers: a Set of Identifier objects
        :param permission_s:  a List of Permission objects

        :returns: a Boolean
        """
        return self.authorizer.is_permitted_all(identifiers, permission_s)

    def check_permission(self, identifiers, permission_s):
        """
        :param identifiers: a collection of identifiers
        :type identifiers: Set

        :param permission_s: a collection of 1..N permissions
        :type permission_s: List of Permission objects or Strings

        :returns: a List of Booleans corresponding to the permission elements
        """
        return self.authorizer.check_permission(identifiers, permission_s)

    def has_role(self, identifiers, roleid_s):
        """
        :param identifiers: a collection of identifiers
        :type identifiers: Set

        :param roleid_s: 1..N role identifiers
        :type roleid_s:  a String or List of Strings

        :returns: a tuple containing the roleid and a boolean indicating
                  whether the role is assigned (this is different than Shiro)
        """
        return self.authorizer.has_role(identifiers, roleid_s)

    def has_all_roles(self, identifiers, roleid_s):
        """
        :param identifiers: a collection of identifiers
        :type identifiers: Set

        :param roleid_s: 1..N role identifiers
        :type roleid_s:  a String or List of Strings

        :returns: a Boolean
        """
        return self.authorizer.has_all_roles(identifiers, roleid_s)

    def check_role(self, identifiers, roleid_s):
        """
        :param identifiers: a collection of identifiers
        :type identifiers: Set

        :param roleid_s: 1..N role identifiers
        :type roleid_s:  a String or List of Strings

        :raises UnauthorizedException: if Subject not assigned to all roles
        """
        return self.authorizer.check_role(identifiers, roleid_s)

    """
    * ===================================================================== *
    * SessionManager Methods                                                *
    * ===================================================================== *
    """
    def start(self, session_context):
        return self.session_manager.start(session_context)

    def get_session(self, session_key):
        return self.session_manager.get_session(session_key)

    """
    * ===================================================================== *
    * SecurityManager Methods                                               *
    * ===================================================================== *
    """

    def create_subject_context(self):
        return DefaultSubjectContext(self.security_utils)

    def create_subject(self,
                       authc_token=None,
                       account=None,
                       existing_subject=None,
                       subject_context=None):

        if not subject_context:
            print('subject_context is NONE')
            context = self.create_subject_context()
            context.authenticated = True
            context.authentication_token = authc_token
            context.account = account
            if (existing_subject):
                context.subject = existing_subject

        else:
            context = copy.copy(subject_context)

        # ensure that the context has a security_manager instance, and if
        # not, add one:
        context = self.ensure_security_manager(context)

        # Resolve an associated Session (usually based on a referenced
        # session ID), and place it in the context before sending to the
        # subject_factory.  The subject_factory should not need to know how
        # to acquire sessions as the process is often environment specific -
        # better to shield the SF from these details:
        context = self.resolve_session(context)

        # Similarly, the subject_factory should not require any concept of
        # remember_me -- translate that here first if possible before handing
        # off to the subject_factory:
        context = self.resolve_identifiers(context)
        subject = self.do_create_subject(context)

        # save this subject for future reference if necessary:
        # (this is needed here in case remember_me identifiers were resolved
        # and they need to be stored in the session, so we don't constantly
        # re-hydrate the remember_me identifier_collection on every operation).
        self.save(subject)
        return subject

    def remember_me_successful_login(self, authc_token, account, subject):
        rmm = self.remember_me_manager
        if (rmm is not None):
            try:
                rmm.on_successful_login(subject, authc_token, account)
            except Exception as ex:
                msg = ("Delegate RememberMeManager instance of type [" +
                       rmm.__class__.__name__ + "] threw an exception "
                       + "during on_successful_login.  RememberMe services "
                       + "will not be performed for account [" + account +
                       "].")
                print(msg)
                # log warn , including exc_info=ex

        else:
            msg = ("This " + rmm.__class__.__name__ +
                   " instance does not have a [RememberMeManager] instance " +
                   "configured.  RememberMe services will not be performed " +
                   "for account [" + account + "].")
            print(msg)
            # log trace here

    def remember_me_failed_login(self, authc_token, authc_exc, subject):
        rmm = self.remember_me_manager
        if (rmm is not None):
            try:
                rmm.on_failed_login(subject, authc_token, authc_exc)

            except Exception as ex:
                msg = ("Delegate RememberMeManager instance of type "
                       "[" + rmm.__class__.__name__ + "] threw an exception "
                       "during on_failed_login for AuthenticationToken [" +
                       authc_token + "].")
                print(msg)
                # log warning here , including exc_info = ex

    def remember_me_logout(self, subject):
        rmm = self.remember_me_manager
        if (rmm is not None):
            try:
                rmm.on_logout(subject)
            except Exception as ex:
                msg = ("Delegate RememberMeManager instance of type [" +
                       rmm.__class__.__name__ + "] threw an exception during "
                       "on_logout for subject with identifiers [{identifiers}]".
                       format(identifiers=subject.identifiers if subject else None))
                print(msg)
                # log warn, including exc_info = ex

    def login(self, subject, authc_token):
        try:
            account = self.authenticate_account(authc_token)
        except AuthenticationException as authc_ex:
            try:
                self.on_failed_login(authc_token, authc_ex, subject)
            except Exception as ex:
                msg = ("on_failed_login method raised an exception.  Logging "
                       "and propagating original AuthenticationException.", ex)
                print(msg)
                # log info here, including exc_info=ex
            raise

        logged_in = self.create_subject(authc_token, account, subject)
        self.on_successful_login(authc_token, account, logged_in)
        return logged_in

    def on_successful_login(self, authc_token, account, subject):
        self.remember_me_successful_login(authc_token, account, subject)

    def on_failed_login(self, authc_token, authc_exc, subject):
        self.remember_me_failed_login(authc_token, authc_exc, subject)

    def before_logout(self, subject):
        self.remember_me_logout(subject)

    def copy(self, securityutils, subject_context):
        return DefaultSubjectContext(securityutils, subject_context)

    def do_create_subject(self, subject_context):
        return self.subject_factory.create_subject(subject_context)

    def save(self, subject):
        try:
            self.subject_store.save(subject)
        except AttributeError:
            msg = "no subject_store is defined, so cannot save subject"
            print(msg)
            # log here
            raise SaveSubjectException(msg)

    def delete(self, subject):
        try:
            self.subject_store.delete(subject)
        except AttributeError:
            msg = "no subject_store is defined, so cannot delete subject"
            print(msg)
            # log here
            raise DeleteSubjectException(msg)

    def ensure_security_manager(self, subject_context):
        try:
            if (subject_context.resolve_security_manager() is not None):
                msg = ("Subject Context already contains a security_manager "
                       "instance. Returning.")
                print(msg)
                # log trace here
                return subject_context

            msg = ("No security_manager found in context.  Adding self "
                   "reference.")
            print(msg)
            # log trace here

            subject_context.security_manager = self

        except AttributeError:
            msg = 'subject_context is invalid'
            print(msg)
            # log exception here
            raise IllegalArgumentException(msg)
        return subject_context

    def resolve_session(self, subject_context):
        if (subject_context.resolve_session() is not None):
            msg = ("Context already contains a session.  Returning.")
            print(msg)
            # log debug here
            return subject_context

        try:
            # Context couldn't resolve it directly, let's see if we can
            # since we  have direct access to the session manager:
            session = self.resolve_context_session(subject_context)
            if (session is not None):
                subject_context.session = session

        except InvalidSessionException as ex:
            msg = ("Resolved subject_subject_context context session is "
                   "invalid.  Ignoring and creating an anonymous "
                   "(session-less) Subject instance.")
            print(msg)
            # log debug here, including exc_info=ex

        return subject_context

    def resolve_context_session(self, subject_context):
        session_key = self.get_session_key(subject_context)

        if (session_key is not None):
            return self.get_session(session_key)

        return None

    def get_session_key(self, subject_context):
        session_id = subject_context.session_id
        if (session_id is not None):
            return DefaultSessionKey(session_id)
        return None

    # yosai omits is_empty method

    def resolve_identifiers(self, subject_context):
        identifiers = subject_context.resolve_identifiers()
        if (not identifiers):
            msg = ("No identity (identifier_collection) found in the "
                   "subject_context.  Looking for a remembered identity.")
            print(msg)
            # log trace here

            identifiers = self.get_remembered_identity(subject_context)

            if identifiers:
                msg = ("Found remembered IdentifierCollection.  Adding to the "
                       "context to be used for subject construction by the "
                       "SubjectFactory.")
                print(msg)
                # log debug here
                subject_context.identifiers = identifiers

            else:
                msg = ("No remembered identity found.  Returning original "
                       "context.")
                print(msg)
                # log trace here

        return subject_context

    def create_session_context(self, subject_context):
        session_context = DefaultSessionContext()

        if (not subject_context.is_empty):
            # TBD:  not sure how acquired attributes are referenced (get vs property)
            session_context.put_all(subject_context)

        session_id = subject_context.session_id
        if (session_id):
            session_context.session_id = session_id

        host = subject_context.resolve_host()
        if (host):
            session_context.host = host

        return session_context

    def logout(self, subject):
        """
        :type subject:  Subject
        """
        if (subject is None):
            msg = "Subject argument cannot be None."
            raise IllegalArgumentException(msg)

        self.before_logout(subject)

        identifiers = subject.identifiers
        if (identifiers):
            msg = ("Logging out subject with primary identifier {0}".format(
                   identifiers.primary_identifier))
            print(msg)
            # log debug here
            authc = self.authenticator
            if (isinstance(authc, authc_abcs.LogoutAware)):
                authc.on_logout(identifiers)

        try:
            self.delete(subject)
        except Exception as ex:
            msg = "Unable to cleanly unbind Subject.  Ignoring (logging out)."
            print(msg)
            # log debug here, including exc_info = ex
        finally:
            try:
                self.stop_session(subject)
            except Exception as ex2:
                msg2 = ("Unable to cleanly stop Session for Subject. "
                        "Ignoring (logging out).", ex2)
                print(msg2)
                # log debug here, including exc_info = ex

    def stop_session(self, subject):
        session = subject.get_session(False)
        if (session):
            session.stop()

    def get_remembered_identity(self, subject_context):
        rmm = self.remember_me_manager
        if rmm is not None:
            try:
                return rmm.get_remembered_identifiers(subject_context)
            except Exception as ex:
                msg = ("Delegate RememberMeManager instance of type [" +
                       rmm.__class__.__name__ + "] raised an exception during "
                       "get_remembered_identifiers().")
                print(msg)
                # log warn here , including exc_info = ex
        return None
