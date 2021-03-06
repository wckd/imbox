import re
import StringIO
import email
import base64, quopri
from email.header import Header, decode_header
from .imap_utf7 import decode as decode_utf7
from .imap_utf7 import encode as encode_utf7

class Struct(object):
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def keys(self):
        return self.__dict__.keys()

    def __repr__(self):
        return str(self.__dict__)

    def __iter__(self):
        return iter(self.__dict__)


def decode_mail_header(value, default_charset='us-ascii'):
    """
    Decode a header value into a unicode string. 
    """
    try:
        headers=decode_header(value)
    except email.errors.HeaderParseError:
        return value.encode(default_charset, 'replace').decode(default_charset)
    else:
        for index, (text, charset) in enumerate(headers):
            try:
                headers[index]=text.decode(charset or default_charset, 'replace')
            except LookupError:
                # if the charset is unknown, force default 
                headers[index]=text.decode(default_charset, 'replace')

        return u"".join(headers)


def get_mail_addresses(message, header_name):
    """
    Retrieve all email addresses from one message header.
    """ 
    addresses = email.utils.getaddresses(header for header in message.get_all(header_name, []))

    for index, (address_name, address_email) in enumerate(addresses):
        addresses[index]={'name': decode_mail_header(address_name), 'email': address_email}

    return addresses


def decode_param(param):
    if param:
	    name, v = param.split('=', 1)
	    values = v.split('\n')
	    value_results = []
	    for value in values:
		    match = re.search(r'=\?(\w+)\?(Q|B)\?(.+)\?=', value)
		    if match:
			    encoding, type_, code = match.groups()
			    if type_ == 'Q':
				    value = quopri.decodestring(code)
			    elif type_ == 'B':
				    value = base64.decodestring(code)
			    value = unicode(value, encoding)
			    value_results.append(value)
	    if value_results: v = ''.join(value_results)
	    return name, v
    else:
        return None 


def parse_attachment(message_part):
    content_disposition = message_part.get("Content-Disposition", None) # Check again if this is a valid attachment
    if content_disposition != None:
        dispositions = content_disposition.strip().split(";")
        
        if dispositions[0].lower() in ["attachment"]:
            file_data = message_part.get_payload(decode=True)

            attachment = {
                'content-type': message_part.get_content_type(),
                'size': len(file_data),
                'content': StringIO.StringIO(file_data)
            }

            for param in dispositions[1:]:
                name, value = decode_param(param)

                if 'file' in  name:
                    attachment['filename'] = value
                
                if 'create-date' in name:
                    attachment['create-date'] = value
            
            return attachment

    return None

def parse_email(raw_email):
    is_dict = True
    data = raw_email
    if type(data) is dict:
        email_message = email.message_from_string(data['data'])
    else: 
        email_message = email.message_from_string(data)
        is_dict = False

    maintype = email_message.get_content_maintype()
    parsed_email = {}

    body = {
        "plain": [],
        "html": [],
    }
    attachments = []


    if maintype == 'multipart':
        for part in email_message.walk():
            content = part.get_payload(decode=True)
            content_type = part.get_content_type()
            content_disposition = part.get('Content-Disposition', None)
            
            if content_type == "text/plain" and content_disposition == None:
                body['plain'].append(content)
            elif content_type == "text/plain" and content_disposition == 'inline':
                body['plain'].append(content)
            if content_type == "text/html" and content_disposition == None:
                body['html'].append(content)
            if content_disposition:
                attachment = parse_attachment(part)
                if attachment: attachments.append(attachment)

    elif maintype == 'text':
        body['plain'].append(email_message.get_payload(decode=True))

    parsed_email['attachments'] = attachments

    parsed_email['body'] = body
    email_dict = dict(email_message.items())

    parsed_email['sent_from'] = get_mail_addresses(email_message, 'from')
    parsed_email['sent_to'] = get_mail_addresses(email_message, 'to')
    for i in parsed_email['sent_to']:
        if 'undisclosed-recipients*' in i:
            i = 'undisclosed@recipients.com'
    parsed_email['cc'] = email_message.get_all('cc')

    value_headers_keys = ['Subject', 'Date','Message-ID', 'Message-Id', 'message-id', 'Message-id']
    key_value_header_keys = ['Received-SPF', 
                            'MIME-Version',
                            'X-Spam-Status',
                            'X-Spam-Score',
                            'Content-Type']

    parsed_email['headers'] = []

    if is_dict:
        """ Add some gmail-specific headers and more to the parsed_email-list """
        for key, value in data.iteritems():
            if key == 'data':
                continue
            valid_key_name = re.sub('-', '_', key.lower())
            parsed_email[valid_key_name] = value
            parsed_email['rfc822'] = data['data']

    for key, value in email_dict.iteritems():
        if key in value_headers_keys:
            valid_key_name = re.sub('-', '_', key.lower())
            parsed_email[valid_key_name] = decode_mail_header(value)
        
        if key in key_value_header_keys:
            parsed_email['headers'].append({'Name': key,
                'Value': value})

    return Struct(**parsed_email)

list_response_pattern = re.compile(r'\((?P<flags>.*?)\) "(?P<delimiter>.*)" (?P<name>.*)')

def parse_list_response(line):
    flags, delimiter, mailbox_name = list_response_pattern.match(line).groups()
    return (flags, delimiter, mailbox_name)

def parse_folders(folders):
    metadata = map(parse_list_response, folders)
    folders = map(decode_utf7, [f[2] for f in metadata])
    return folders
