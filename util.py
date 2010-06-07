import os
import sys
import imp
import Cookie
import threading
import mimetypes
import functools

class DefaultLocal(threading.local):
    environ = {}

local = DefaultLocal()

class WakaError(Exception):
    '''Error to be reported to the user'''
    def __init__(self, message, fromwindow=False):
        self.message = message
        self.fromwindow = fromwindow

    def __str__(self):
        return self.message

def wrap_static(application, *app_paths, **kwds):
    '''Application used in the development server to serve static files
    (i.e. everything except the CGI filename). DO NOT USE IN PRODUCTION'''
    
    @functools.wraps(application)
    def wrapper(environ, start_response):
        filename = environ['PATH_INFO'].strip('/')

        if filename in app_paths or not filename:
            environ['SCRIPT_NAME'] = '/' + filename
            return application(environ, start_response)

        if os.path.isdir(filename):
            index = kwds.get('index', 'index.html')
            filename = os.path.join(filename, index)

        if os.path.exists(filename):
            content, encoding = mimetypes.guess_type(filename)
            headers = [('Content-Type', content),
                       ('Content-Encoding', encoding)]
            start_response('200 OK', [x for x in headers if x[1]])
            return open(filename)
        else:
            handler = kwds.get('not_found_handler', None)
            if handler:
                return handler(environ, start_response)
            start_response('404 Not found', [('Content-Type', 'text/plain')])
            return ['404 Not found: %s' % filename]
    
    return wrapper

def module_default(modulename, defaults):
    '''Set default values to modulename
    Keys which start with underscores are ignored'''

    module = __import__(modulename)
    for key in defaults:
        if not key.startswith('_') and not hasattr(module, key):
            setattr(module, key, defaults[key])

def import2(name, path):
    '''Imports a module from path without requiring a __init__.py file'''

    fullname = '%s.%s' % (path, name)

    if fullname in sys.modules:
        return sys.modules[fullname]
    else:
        modinfo = imp.find_module(name, [path])
        module = imp.load_module(fullname, *modinfo)
        modinfo[0].close() # the docs say i must close this :(
        return module

def headers(f):
    '''Decorator that allows sending output without calling start_response
    It replaces start_response with a backwards-compatible version that
    doesn't do anything if called more than once.'''

    @functools.wraps(f)
    def wrapper(environ, start_response):
        environ['waka.status'] = '200 OK'
        environ['waka.headers'] = {'Content-Type': 'text/html'}
        environ['waka.response_sent'] = False
        environ['waka.cookies'] = Cookie.BaseCookie()

        def new_start_response(status, headers):
            if environ['waka.response_sent']:
                return
            environ['waka.response_sent'] = True

            # merge parameter headers with the environ ones
            environ['waka.headers'].update(dict(headers))

            # Set-cookie can be repeated, so it's handled separately
            headerlist = environ['waka.headers'].items()
            for cookie in environ['waka.cookies']:
                headerlist.append(tuple(cookie.output().split(": ", 1)))

            start_response(status, headerlist)
            
        appiter = f(environ, new_start_response)
        new_start_response(environ['waka.status'], environ['waka.headers'])
        return appiter
    return wrapper

def cleanup(application, cleanup_function):
    '''Pseudo-decorator that calls a cleanup function always after an app
    is run. This is needed because the apps may return the iterator before
    execution is done'''

    @functools.wraps(application)
    def wrapper(environ, start_response):
        try:
            appiter = application(environ, start_response)
            for item in appiter:
                yield item
        finally:
            cleanup_function(environ, start_response)
    return wrapper

def make_http_forward(location, alternate_method=False):
    '''Pseudo-application to redirect to another location'''
    if alternate_method:
        return ['<html><head>'
                '<meta http-equiv="refresh" content="0; url=%s" />'
                '<script type="text/javascript">document.location="%s";</script>'
                '</head><body><a href="%s">%s</a></body></html>' % 
                ((location, ) * 4)]
    else:
        local.environ['waka.status'] = '303 Go West'
        local.environ['waka.headers']['Location'] = location
        return ['<html><body><a href="%s">%s</a></body></html>' %
                ((location, ) * 2)]
