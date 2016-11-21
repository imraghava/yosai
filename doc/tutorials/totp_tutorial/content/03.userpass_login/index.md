+++
chapter = true
date = "2016-11-20T15:16:01-05:00"
icon = "<b>X. </b>"
next = "/next/path"
prev = "/prev/path"
title = "UserPass Login"
weight = 10

+++

# TOTP Authentication Step 1:  User Login

Client is prompted with a standard login form to enter a username and password.
Client submits the requested information to the server, authenticating itself.

![username_password_login](img/username_password_login.jpg)


### Server First Authentication Request:  UsernamePasswordToken

```python
    with Yosai.context(yosai):
        new_subject = Yosai.get_current_subject()

        password_token = UsernamePasswordToken(username='thedude',
                                               credentials='letsgobowling')
        try:
            new_subject.login(password_token)
        except AdditionalAuthenticationRequired:
            # this is where your application responds to the second-factor
            # request from Yosai
            # this is pseudocode:
            request_totp_token_from_client()
        except IncorrectCredentialsException:
            # incorrect username/password provided
        except LockedAccountException:
            # too many failed username/password authentication attempts, account locked
```