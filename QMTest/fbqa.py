﻿########################################################################
#
# File:   fbqa.py
# Date:   2004-06-10
#
# Contents:
#   Common, Test and Resource classes and function for Firebird QA
#
# Contributors: Moe Aboulkheir
#               Pavel Cisar
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
########################################################################

########################################################################
# imports
########################################################################

import sys, os, string, re, difflib, kinterbasdb as kdb, struct, cgi
from StringIO import StringIO
import pdb

import qm
import qm.common
import qm.fields
import qm.test.base
import qm.executable
import qm.test.base
from   qm.test.result   import *
from   qm.test.test     import *
from   qm.test.resource import *
import qm.web

########################################################################
# globals
########################################################################

try:
    import hermann_colorize
except ImportError:
    # Python code colorization is just a luxury, not a necessity.
    hermann_colorize = None
else:
    # Reset the colors to a less garish scheme (this relies on underscored
    # vars, so it might cause trouble as hermann_colorize evolves).
    hermann_colorize._colors = {
        hermann_colorize.token.NUMBER:       '#666600',
        hermann_colorize.token.OP:           '#7D0000',
        hermann_colorize.token.STRING:       '#8F8C71',
        hermann_colorize.tokenize.COMMENT:   '#50A550',
        hermann_colorize.token.NAME:         '#000000',
        hermann_colorize.token.ERRORTOKEN:   '#FF8080',
        hermann_colorize._KEYWORD:           '#0D0DBB',
        hermann_colorize._TEXT:              '#000000',
      }

# Next code hijacks the method qm.web.DtmlPage.GenerateHtmlHeader, 
# replacing it with a custom implementation that specifies the character set 
# of returned pages as UTF-8 rather than QMTest's default of ISO-8859-1.
# This might be thought of as a "hot fix" to allow better unicode integration
# while still using the standard distribution of QMTest.

# Establish and hold a reference to the original implementation of
# GenerateHtmlHeader, lest it be garbage collected when we overwrite its
# class's reference to it.
_ORIGINAL_IMPL = qm.web.DtmlPage.GenerateHtmlHeader

def GenerateHtmlHeader(self, description, headers=''):
    header = _ORIGINAL_IMPL(self, description, headers=headers)
    header = header.replace('charset=iso-8859-1', 'charset=utf-8')
    return header

qm.web.DtmlPage.GenerateHtmlHeader = GenerateHtmlHeader

# Python 2.2 and earlier require either ASCII or ISO-8859-1 encoding of source
# files.
PYTHON_SUPPORTS_SOURCE_ENCODINGS = sys.version_info >= (2,3)
_SOURCE_ENCODING_SPEC = u'# -*- coding: UTF8 -*-\n'

_WHITE_BG = '<div style="background-color: white; margin: 0px;">%s</div>'
_WHITE_BG_U = unicode(_WHITE_BG,'UTF8')
_PRE_NO_MARGIN = '<pre style="margin: 0px;">%s</pre>'

# isc_database_info call requests
# commented out ones were not documented, so they're not supported now

isc_info_page_errors             = 54
isc_info_record_errors           = 55
isc_info_bpage_errors            = 56
isc_info_dpage_errors            = 57
isc_info_ipage_errors            = 58
isc_info_ppage_errors            = 59
isc_info_tpage_errors            = 60
isc_info_db_sql_dialect          = 62
isc_info_attachment_id           = 22
isc_info_set_page_buffers        = 61
isc_info_db_read_only            = 63
isc_info_db_size_in_pages        = 64
#frb_info_att_charset             = 101
#isc_info_db_class                = 102
isc_info_firebird_version        = 103
isc_info_oldest_transaction      = 104
isc_info_oldest_active           = 105
isc_info_oldest_snapshot         = 106
isc_info_next_transaction        = 107
#isc_info_db_provider             = 108
#isc_info_active_transactions     = 109

_PRE = '<pre>%s</pre>'


########################################################################
# classes
########################################################################

class SubstitutionField(qm.fields.TupleField):
  """A rule for performing a text substitution.

     A 'SubstitutionField' consists of a regular expression pattern and a
     corresponding replacement string.  When the substitution is applied
     to a body of text, all substrings that match the pattern are
     replaced with the substitution string.

     The syntax for the regular expression and the substitution string is
     that of the standard Python 're' (regular expression) module."""

  def __init__(self, name, **properties):
    """Create a new 'SubstitutionField'.

       By default, the pattern and replacement string are empty."""
    # Initialize the base class.
    fields = [UnicodeField(name = "pattern",
                                  title = "Pattern",),
              UnicodeField(name = "replacement",
                                  title = "Replacement")]
    qm.fields.TupleField.__init__(self, name, fields, **properties)


  def GetHelp(self):
    return """
        A substitution consists of a regular expression pattern and a
        substitution string.  When the substitution is applied, all
        subtrings matching the pattern are replaced with the
        substitution string.  The substitution string may reference
        matched groups in the pattern.

        The regular expression and substitution syntax are those of
        Python's standard "'re' regular expression module"."""

class UnicodeField(qm.fields.TextField):
    """
      A subclass of 'TextField' that supports Unicode.
    """

    def FormatValueAsHtml(self, server, value, style, name=None):
        # $value is typically unicode rather than str.  In any case, we always
        # encode the returned HTML code in UTF-8.
        #
        # qm.fields.TextField.FormatValueAsHtml can't handle Unicode, so
        # we replace $value with a flag, call the super-method, convert
        # the resulting HTML str into a unicode object, replace the flag
        # with the real $value, then encode $value in UTF-8 for
        # transmission to the client.
        flag = '_______REPLACE_THIS_FLAG_______'
        html = qm.fields.TextField.FormatValueAsHtml(self, server, flag, style, name=name)
        # Next try-except is necessary for QMTest. When test is loaded for edit,
        # the value content is ok, but if test editing form contains button
        # (for example to add/remove substitution definition) and this button is
        # used, the form reload logic goes in different route, and value has encoding
        # that replace cannot handle. This case is handled by except part.
        try:
          html = unicode(html,'UTF8').replace(flag, value)
        except UnicodeError:
          html = unicode(html,'UTF8').replace(flag, unicode(value,'UTF8'))
            
        return html.encode('UTF8')


class PythonCodeField(UnicodeField):
    """
      A subclass of 'TextField' that supports Unicode and colorizes its 
      contents as Python source code.
    """

    def FormatValueAsHtml(self, server, value, style, name=None):
        # $value is typically unicode rather than str.  In any case, we always
        # encode the returned HTML code in UTF-8.
        if style != 'full':
            html = UnicodeField.FormatValueAsHtml(self, server, value, style, name=name)
        else:
            colorized = _colorizePython(value)
            html = (_WHITE_BG_U % colorized).encode("UTF8")

        return html


class FirebirdTest(Test):
  """Multipurpose class for performing common Firebird quality assurance procedures"""

  arguments = [
   qm.fields.TextField(
        name="test_id",
        title="Test ID",
        not_empty_text=1,
        description="""An unique ID assigned to test.

        The ID is usualy constructed as author's name and sequence number.
        For example: pcisar_001"""
        ),

    qm.fields.TextField(
        name="author",
        title="Author",
        not_empty_text=1,
        description="""Author's nickname.

        Use the nickname listed in AUTHORS.TXT. For new test authors, don't forget
        to add appropriate record (nickname and e-mail) in this file!

        If test has multiple authors, list their nicknames separated by colon.
        """
        ),

   qm.fields.TextField(
        name="target_version",
        title="Target Engine",
        not_empty_text=1,
        default_value="1.0",
        description="""Version number for engine that this test is designed for.

        Each Firebird (final) release has an unique Version Number assigned by Project.
        This version number is constructed as a dot-separated release version number, where first number
        represents major Firebird version, second number represents a minor version, third number
        represents an update number, and last, fourth number represents a build number.

        This value is used by qaver.py tool to create test database for given engine version.
        """
        ),

    qm.fields.TextField(
        name="target_platform",
        title="Target Platform",
        not_empty_text=1,
        default_value="All",
        description="""List of target platforms that this test is designed for, separated by colon (default All)

        This value is used by qaver.py tool to create test database for given platform. Use only next
        values: Windows, Linux, Solaris, HP-UX, FreeBSD, Darwin and Sinix-Z"""
        ),

    qm.fields.TextField(
        name="bug_id",
        title="Bug identifier",
        description="""Bug Identifier

        If this test covers a bug, it should have a bug tracker entry.
        Enter the ID from bug tracker here (usualy a number)."""
        ),

    UnicodeField(
        name="title",
        title="Title",
        not_empty_text=1,
        description="""Short descriptive title.

        This is a short, descriptive name for test. Should describe what's tested.
        For example: ALTER DATABASE ADD FILE"""
        ),

    UnicodeField(
        name="description",
        title="Description",
        verbatim="true",
        multiline="true",
        description="""Full test description.

        Please describe how the test is supposed to work, what's tested and how,
        possible points of failure etc."""
        ),

    qm.fields.EnumerationField(
        name="create_db_method",
        title="Database Creation Method",
        description="""Connect to existing database, create new database or restore database from backup

        If "Create New" is chosen, kinterbasdb will be used to create a database with the given parameters.
        A connection to the database will then be made with kinterbasdb.

        if "Connect to existing" is chosen, kinterbasdb will be used to connect to the given database using
        the given parameters.

        if "Restore from Backup" is chosen, gbak will be used to restore a database with the given name from
        the given backup file.  If the database already exists, the test will raise an error.

        if "None" is chosen, then test hasn't any assumption about use of any database in test.""",
        enumerals=["Create New", "Connect To Existing", "Restore From Backup", "None"],
        default_value="Create New"
        ),

    qm.fields.TextField(
        name="db_path_property",
        title="Database Path Property Name",
        description="The name of the context property which is set to the path to the database",
        default_value="database_location"
        ),

    qm.fields.TextField(
        name="db_name",
        title="Database Name",
        description="""The Database name.

        This value is concatenated with the server and database locations from context file""",
        default_value="database_name"
        ),

    qm.fields.TextField(
        name="backup_file_path",
        title="Path to Backup File",
        description="The backup file to be used (if database is to be restored from backup)"
        ),

    qm.fields.TextField(
        name="user_name",
        title="User Name",
        description="""The user name to use to access to the database

        If the database already exists, this will be assumed to be the username granting access
        to the database.  If the database is being created, then this fields value will be set as the
        username""",
        default_value="SYSDBA"
        ),

    qm.fields.TextField(
        name="user_password",
        title="User Password",
        description="""The password to use to access the database

        If the database already exists, this will be assumed to be the password granting access
        to the database.  If the database is being created, then this fields value will be set as the
        password""",

        default_value="masterkey"
        ),

    qm.fields.EnumerationField(
        name="character_set",
        title="Character Set",
        description="Character set to use for database connection",
        enumerals = ["NONE","ASCII","BIG_5","CYRL","DOS437","DOS850","DOS852",
                     "DOS857","DOS860","DOS861","DOS863","DOS865","EUCJ_0208","GB_2312",
                     "ISO8859_1","KSC_5601","NEXT","OCTETS","SJIS_0208","UNICODE_FSS",
                     "WIN1250","WIN1251","WIN1252","WIN1253","WIN1254","LATIN2"],
        default_value="NONE",
        ),

    qm.fields.EnumerationField(
        name="page_size",
        title="Page Size",
        description="Page size for database (if database is being created).  Defaults to 4096",
        enumerals = ["Default","1024","2048","4096","8192","16384"],
        default_value="Default",
        ),

    qm.fields.EnumerationField(
        name="sql_dialect",
        title="SQL Dialect",
        description="""The SQL dialect to use
        
        The connect and/or create statements will be executed using this dialect.""",
        enumerals = ["1","2","3"],
        default_value="3",
        ),
        
    qm.fields.EnumerationField(
        name="populate_method",
        title="Database Population Method",
        description="""This field determines how the database will be populated
            
        Possible options are "Using SQL Commands", "Using Data Tuple" and "None (manual)".
        
        If "Using SQL Commands" is selected, then the field "SQL Commands" must be defined.
          The contents of that field will be executed as an SQL script (using ISQL) in the context of the
         database associated with this test
         
        If "Using Data Tuple" is selected, then the fields "Data Tuple" and "SQL Insert Statement" must 
        be defined.  The "SQL Insert Statement" will be interpreted as a parameterized SQL insert statement 
        and will be executed using kinterbasdb with the given data tuples values as its parameters.""",
        enumerals= ["Using Data Tuple", "Using SQL Commands", "None (manual)"],
        default_value="None (manual)"
        ),
            
    qm.fields.TextField(
        name="isql_script",
        title="SQL Commands",
        description="""The SQL commands to use to populate the database (if that option was selected above)
        
        These commands will be written to a file and executed using ISQL, in the context of the database
        associated with this test.""",
        multiline="true",
        verbatim="true"
        ),
        
            
    UnicodeField(
        name="data_tuple",
        title="Data Tuple",
        description="""Data tuple to populate database with (if that option was selected above)
        
        The data tuple given in this field will be used to provide the parameters to the SQL insert
        statement.
        This field needs to be a tuple of tuples or a list of lists.
        Example: ( ("Jane", 23), ("Sam", 56) ) or [ ["Sally", 21], ]""",
        multiline="true",
        verbatim="true"
        ),
        
    qm.fields.TextField(
        name="insert_statement",
        title="SQL Insert Statement",
        description="""The parameterized SQL insert statement to use with the data tuple (if that option was selected above)

        The variable parameters given in this statement will be provided by the data tuple given above.
        This statement must be parameterized and include the same number of parameters as each tuple
        in the data tuple.
        Example: "insert into people values (?, ?)" """
        ),

    qm.fields.EnumerationField(
        name="statement_type_and_result",
        title="Test Statement Type and Expected Return Type",
        description="""The test statement type (Python/SQL) and expected return type (boolean/string)

        if "Python: True" or "Python: False" is selected, python source code can be supplied to be
        executed prior to the evaluation of the test statement.  outside of catching thrown exceptions,
        no checking is performed on the return value(s) of the source code, Because of this, the test
        statement is what is being evaluated for truth.

        if "Python: String" is selected, the standard output stream (if any) generated by the python
        source code will be captured and compared against the given string.  if a python test statement is
        given, then the python source code will be executed but it's output will be ignored, and the output
        of the test statement will be captured and compared against the given result string.

        if "SQL: String" is selected, then the given SQL command(s) entered in the source code field will
        be executed using ISQL in the context of the database associated with this test, and the output
        (if any) compared with the given string(s).""",

        enumerals=["None: None", "Python: True", "Python: False", "Python: String", "SQL: String"],
        default_value="None: None"
        ),

    PythonCodeField(
        name="source_code",
        title="Python/SQL Source Code",
        description="""The SQL or python test statement(s) to be executed

        If "Python: True" or "Python: False" was selected as the type/expected return value of the test
        statement, then the contents of this field are optional, and will be executed before the test
        statement itself (which is required) is evaluated for truth.  In this case any values or output
        returned or generated by this code will be ignored (unless any exceptions are thrown).  The active
        connection to the database associated with this test is available in the namespace of the source
        code as "db_conn".  The test's context is available as "context" and kinterbasdb is also present
        as "kdb".

        If "Python: String" was selected as the type/expected return value of the test statement, then any
        output generated by this code will be compared against the given string(s).  The only exception to
        this rule is if a test statement is given below.  In that case, this code will be executed but the
        output of the test statement (and not this source code) is what will be compared against the given
        result string.  The active connection to the database associated with this test is available in the
        namespace of the source code as "db_conn".  The test's context is available as "context" and
        kinterbasdb is also present as "kdb".

        If "SQL: String" was selected as the type/expected return value of the test statement, then the
        contents of this field will be executed an ISQL script in the context of the database associated
        with this test.""",

        multiline="true",
        verbatim="true"
        ),

    PythonCodeField(
        name="test_expr",
        title="Python Expression",
        description="""The python statement to evaluate

        If "Python: True" or "Python:False" was selected as the type/expected return value of the test
        statement, then after the python source code is executed (if any was given), the value of this
        statement will be compared against the selected True/False value

        If "Python: String" was selected then this field is optional.  If it is given a value, then after
        the python source code is executed (if any was given), the standard output from this statement will
        be captured and compared against the given string

        The active connection to the database associated with this test is available in the namespace of the
        source code as "db_conn".
        The test's context is available as "context" and kinterbasdb is also present as "kdb".
        """,
        multiline="true",
        verbatim="true"
        ),

    UnicodeField(
        name="result_string",
        title="Expected Result String",
        description="""The expected result string for the test statement(s) (if not a boolean)

        If "SQL: String" or "Python: String" was selected as the type/expected return value
        of the test statement, then the output generated by Python or SQL will be compared against the text
        given here.

        If any regular expression substitutions are provided below, they will be applied to both the
        expected and actual outputs of the SQL/python expressions.  if any differences exist between the
        expected/actual outputs, then a diff will be provided as an annotation to the test results.""",
        multiline="true",
        verbatim="true"
        ),

    UnicodeField(
        name="expected_stderr",
        title="Expected stderr",
        description="""The expected Standard Error output for the test statement(s) (if not a boolean)

        If "SQL: String" was selected as the type/expected return value of the test statement, then the
        error output generated by SQL will be compared against the text given here.

        If any regular expression substitutions are provided below, they will be applied to both the
        expected and actual error outputs of the SQL expressions.  if any differences exist between the
        expected/actual outputs, then a diff will be provided as an annotation to the test results.""",
        multiline="true",
        verbatim="true"
        ),

    qm.fields.SetField(SubstitutionField(
        name="substitutions",
        title="Substitutions",
        description="""Regular expression substitutions.

        Each substitution will be applied to both the expected and
        actual stdout of the expressions.  The comparison will be
        performed after the substitutions have been performed.

        You can use substitutions to ignore insignificant
        differences between the expected and actual outputs.""")),

    qm.fields.BooleanField(
        name="drop_db",
        title="Drop Database?",
        description="""This field determines whether or not the database will be dropped

        If this field is set to "true", then prior to exiting, the database will be removed.  This is still
        applicable if the test fails or raises an exception during execution.  If the database cannot be
        dropped, and the test has already failed or generated an error for some other reason, then the
        location of the database will be given as an annotation to the result.  it is important the database
        is then removed manually as subsequent tests may fail if they attempt to create a database with the
        same name.""",
        default_value="true")

  ]

  def __MakeEnvironment(self):
    """Construct the environment for executing the target program."""
    environment= os.environ.copy()

    for key, value in self.__context.items():
      if type(value) is str:
        name = "QMV_" + key.replace(".", "__")
        environment[name]= value

    return environment

  def __SubstituteMacros(self,text):
    # Substitute macros for context values
    f_text = text
    c = {}
    for pair in self.__context.items():
        c[pair[0]] = pair[1]
    for substitution in c.keys():
        pattern = "$("+substitution.upper()+")"
        replacement = self.__context[substitution]
        f_text = f_text.replace(pattern, replacement)
    return f_text

  def __RunProgram(self, stdin, args):
    environ= self.__MakeEnvironment()

    # PC: fix values so they are strings. Needed for Windows.
    for key in environ.iterkeys():
      environ[key] = str(environ[key])

      self.__cause= "Unknown cause"

    basename   = os.path.split(args[0])[-1]
    qm_exec    = qm.executable.Filter(self.__SubstituteMacros(stdin+"\n"), -2)

    exit_status= qm_exec.Run(args, environ)

    if sys.platform == "win32" or os.WIFEXITED(exit_status):
      return qm_exec.stdout, qm_exec.stderr

    elif os.WIFSIGNALED(exit_status):
      self.__cause= "Process %s terminated by signal %d." % (basename, os.WTERMSIG(exit_status))

    elif os.WIFSTOPPED(exit_status):
      self.__cause= "Process %s stopped by signal %d." % (basename, os.WSTOPSIG(exit_status))

    else:
      self.__cause= "Process %s terminated abnormally." % basename


  def __KCreateDB(self):
    """Use kinterbasdb to create database using options defined by test."""
    if self.create_db_method == "Create New":
      if self.page_size == "Default":
        createCommand = "CREATE DATABASE '%s' USER '%s' PASSWORD '%s'" % (self.__dsn,
                                                                         self.user_name,
                                                                         self.user_password)
      else:
        createCommand = "CREATE DATABASE '%s' USER '%s' PASSWORD '%s' PAGE_SIZE=%d" % (self.__dsn,
                                                                         self.user_name,
                                                                         self.user_password,
                                                                         int(self.page_size))
      try:
        conn= kdb.create_database(createCommand, int(self.sql_dialect))

        conn.close()

      except:
        self.__result.NoteException(cause="Exception raised while creating database.")
        return

  def __KConnectDB(self):
    """Use kinterbasdb to connect to database using options defined by test.

       "self.__context" = test's run-time self.__context (dictionary)
       "self.__result"  = QM result object"""
    try:
      conn= kdb.connect(dsn     = self.__dsn,
                        user    = self.user_name.encode(),
                        password= self.user_password.encode(),
                        charset = self.character_set.encode(),
                        dialect = int(self.sql_dialect))
    except:
      self.__result.NoteException(cause="Exception raised while connecting to database.")
    else:
      return conn
      
  def __InsertParam(self):
    try:
      cursor= self.__db_conn.cursor()
      cursor.executemany(self.insert_statement, self.data_tuple)
      self.__db_conn.commit()
    except:
      self.__result.NoteException(cause="Exception raised while INSERTing data tuple.")
    else:
      return True
    
    
  def __WriteToFile(self, fname, contents):
    script_path= self.__context["temp_directory"] + fname
    try:
      fhandle= open(script_path, "w")
    except:
      self.__result.NoteException(cause="Exception raised opening file <i>%s</i> for writing." % script_path)
    else:
      fhandle.write(contents + "\n")
      fhandle.close()
      self.__clean_up.append(script_path)
      return script_path
      
  def __ExecISQLCommandsBlind(self):

    try:
      stdout, stderr= self.__RunProgram(self.isql_script,[self.__context["isql_path"],
                                         self.__dsn,
                                         "-user",     self.user_name,
                                         "-password", self.user_password])

    except:
      # if __RunProgram couldn't run the program, it will return nothing
      # (raising an exception when we try to assign the return value)
      # whatever went wrong will be stored in "self.__cause"
      self.__result.Fail(cause= self.__cause)

    else:
      if stderr:
        self.__AnnotateStream(stderr, "STDERR", "ISQL")
      else:
        return True
                               
                                           
  def __ExecISQLCommands(self):
    """Execute given ISQL commands. This method needs to have arguments passed
       to it because there is more than one field in the test which might
       require execution as an ISQL script.

       "commands" = the commands to be executed (string)
       "sub_map"  = the map of regex substitutions to perform (dict)"""

    try:
      stdout, stderr= self.__RunProgram(self.source_code,[self.__context["isql_path"],
                                         self.__dsn,
                                         "-user",     self.user_name,
                                         "-password", self.user_password])

    except:
      self.__result.Fail(cause= self.__cause)
      exc_info = sys.exc_info()
      self.__result[Result.EXCEPTION]= "%s: %s" % exc_info[:2]

    else:

      stdout_stripped= self.__StringStrip(stdout) # strip whole stdout
      stdout_e_stripped= self.__StringStrip(self.result_string) # strip whole expected stdout
      stderr_stripped= self.__StringStrip(stderr) # strip whole stderr
      stderr_e_stripped= self.__StringStrip(self.expected_stderr) # strip whole expected stderr

      if stderr_stripped != stderr_e_stripped: # if error outputs do not match
        self.__AnnotateErrorDiff("ISQL",
                            self.expected_stderr,
                            stderr,
                            stderr_e_stripped,
                            stderr_stripped)
      elif stdout_stripped == stdout_e_stripped: # if they match
        return True # ok
      else:

        self.__AnnotateDiff("ISQL",
                            self.result_string,
                            stdout,
                            stdout_e_stripped,
                            stdout_stripped)


  def __FileStrSame(self, fhandle, mstr, isql=True):
    fhandle.seek(0)
    line_list= mstr.splitlines()
    SAME= True

    for line in fhandle.xreadlines(): # read a line
      line= self.__StringStrip(line[:-1], isql= isql)

      if not line: # if its a blank, skip it.  we do this because the only
        continue   # real difference between doing the regex subs line by
                   # line (which we have to do to avoid reading the whole
                   # stdout into memory) and on an entire string, is that
                   # when performed on an entire string, there will be no
                   # blank lines

      try:
        cmp_line= line_list.pop(0) # remove and store the first remaining

      except:                      # line from the line list
        SAME= False
        break                      # if we're out of lines, then the comparison
                                   # fails because we wouldnt still be in this
                                   # loop unless there was at least one pending,
                                   # non-blank line in the file


      if line != cmp_line:         # if the lines arent the same, the loop exits
        SAME= False                # and saves the failed status
        break

    if line_list:                  # if we finished reading lines from the file
      SAME= False                  # and there are still un pop()'ed lines in the list,
                                   # then the comparison fails.
    fhandle.seek(0)
    return SAME


  def __EncloseList(self, alist):
    # enclose each line into doublequotes to see trailing blanks
    return '"'+'"\n"'.join(alist.splitlines())+'"'

  def __AnnotateDiff(self, desc, stdout_e, stdout_a, stdout_e_strp, stdout_a_strp):
    id_str= "FirebirdTest.%s_" % desc # (i.e. FirebirdTest.ISQL_*)

    self.__result[id_str + "stdout_expected"]         = _PRE % stdout_e.encode('UTF8')
    self.__result[id_str + "stdout_actual"]           = _PRE % stdout_a
    self.__result[id_str + "stdout_expected_stripped"]= _PRE % stdout_e_strp
    self.__result[id_str + "stdout_actual_stripped"]  = _PRE % stdout_a_strp
    self.__result[id_str + "stripped_diff"]= _PRE % string.join( difflib.ndiff( stdout_e_strp.splitlines(),
                                                                         stdout_a_strp.splitlines() ), "\n")

    self.__result.Fail("Expected standard output from %s does not match actual output." % desc)

  def __AnnotateErrorDiff(self, desc, stderr_e, stderr_a, stderr_e_strp, stderr_a_strp):
    id_str= "FirebirdTest.%s_" % desc # (i.e. FirebirdTest.ISQL_*)

    self.__result[id_str + "stderr_expected"]         = _PRE % stderr_e
    self.__result[id_str + "stderr_actual"]           = _PRE % stderr_a
    self.__result[id_str + "stderr_expected_stripped"]= _PRE % stderr_e_strp
    self.__result[id_str + "stderr_actual_stripped"]  = _PRE % stderr_a_strp
    self.__result[id_str + "stderr_stripped_diff"]= _PRE % string.join( difflib.ndiff( stderr_e_strp.splitlines(),
                                                                         stderr_a_strp.splitlines() ), "\n")

    self.__result.Fail("Expected error output from %s does not match actual error output." % desc)

  def __StringStrip(self, string, isql=True):
    """Strip command prompts and superfluous whitespace which might cause
       comparisons to fail on insignificant differences

       "string" = string to strip (string)"""
    if not string:
      return string

    if isql:
      for regex in self.__isqlsubs:
        string= re.sub(regex, "", string)

    for pattern, replacement in self.substitutions:
      string= re.compile(pattern.encode('UTF8'), re.M).sub(replacement.encode('UTF8'), string)
    
    return self.__SpaceStrip(string)

  def __SpaceStrip(self, string):
    string= re.sub("(?m)^\s+", "", string)
    return re.sub("(?m)\s+$", "", string)
      
        
  def __RestoreBackup(self):
    try:
      stdout, stderr= self.__RunProgram([self.__context["gbak_path"], "-C", self.backup_file_path, self.__db_path])
    except:
      # if __RunProgram couldn't run the program, it will return nothing
      # (raising an exception when we try to assign the return value)
      # whatever went wrong will be stored in "self.__cause"
      self.__result.Fail(cause= self.__cause)
      return
      
    else:
      if stdout or stderr:
        self.__AnnotateStreams(stdout, stderr, "GBAK")
      else:
        return True
        
 
  def __AnnotateStream(self, stream, sname, pname):
    self.__result["FirebirdTest.%s_%s" % (pname, sname)]= stream
    self.__result.Fail(cause="Expected %s stream received from %s." % (sname, pname))
    
  def __AnnotateStreams(self, stdout, stderr, pname):
    unexp=[]

    if stdout:
      unexp.append("stdout")
      self.__result["FirebirdTest.%s_STDOUT" % pname]= stdout
    
    if stderr: # gbak prints nothing to stderr if everything went ok
      unexp.append("stderr")
      self.__result["FirebirdTest.%s_STDERR" % pname]= stderr
      
    if unexp: # if we got something in stdout, stderr or both 
      cause= "Unexpected " + " and ".join(unexp) + " stream%s " % "s"[len(unexp)==1:] + "received from %s." % pname
      self.__result.Fail(cause= cause)
      
  def __ExecPythonBool(self):
    global_ns, local_ns= self.__MakeNamespaces()
    
    retval_e= eval(self.statement_type_and_result[8:])
    # self.statement_type_and_result[8:] will be "True" or "False"
    
    try:
        if self.__context.has_key("debug"):
          dbgfname = self.__context["temp_directory"] + "debug.python"
          self.__clean_up.append(dbgfname)
          dbgfile = open(dbgfname,"w")
          src = '# -*- coding: UTF8 -*-\n'+self.__SubstituteMacros(self.source_code)+"\n"
          dbgfile.write(src.encode("utf-8"))
          dbgfile.close()
          c = compile(src.encode("utf-8"),dbgfname,"exec")
          pdb.run(c, global_ns, local_ns)
        else:
          exec self.__SubstituteMacros(self.source_code) in global_ns, local_ns
    
    except:
      self.__result.NoteException(cause="Exception raised while executing python source code.")
      return
      
    if self.test_expr:
      try:
        if self.__context.has_key("debug"):
          dbgfname = self.__context["temp_directory"] + "debug.python"
          self.__clean_up.append(dbgfname)
          dbgfile = open(dbgfname,"w")
          src = '# -*- coding: UTF8 -*-\n'+self.__SubstituteMacros(self.test_expr)+"\n"
          dbgfile.write(src.encode("utf-8"))
          dbgfile.close()
          c = compile(src.encode("utf-8"),dbgfname,"eval")
          pdb.runeval(c, global_ns, local_ns)
        else:
          retval_a= eval(self.test_expr, global_ns, local_ns)
      
      except:
        self.__result.NoteException(cause="Exception raised while evaluating python expression.")
        return
      
      else:
        if retval_a == retval_e:
          return True # let caller know everything went OK
        else:
          self.__result.Fail("Python expression evaluates to %d." % retval_a)
          self.__result["FirebirdTest.expected_value_python"]= str(retval_e)
          return
          
          
  def __ExecPython(self):
    global_ns, local_ns= self.__MakeNamespaces()

    saved_out      = sys.stdout

    try:
      if self.test_expr:
        exec self.__SubstituteMacros(self.source_code) in global_ns, local_ns

        try:
          sys.stdout= StringIO()
          exec self.__SubstituteMacros(self.test_expr) in global_ns, local_ns

        except:
          result.NoteException(cause="Exception raised while executing python expression.")
          return
      else:
        if self.__context.has_key("debug"):
          dbgfname = self.__context["temp_directory"] + "debug.python"
          self.__clean_up.append(dbgfname)
          dbgfile = open(dbgfname,"w")
          src = '# -*- coding: UTF8 -*-\n'+self.__SubstituteMacros(self.source_code)+"\n"
          dbgfile.write(src.encode("utf-8"))
          dbgfile.close()
          c = compile(src.encode("utf-8"),dbgfname,"exec")
          pdb.run(c, global_ns, local_ns)
        else:
          sys.stdout= StringIO()
          exec self.__SubstituteMacros(self.source_code) in global_ns, local_ns

    except:
      self.__result.NoteException(cause="Exception raised while executing python source code.")
    else:
      if not self.__context.has_key("debug"):
        try:
          stdout_a= sys.stdout.getvalue()
          stdout_a= stdout_a.encode('UTF8')
        except  UnicodeDecodeError:
          pass
      else:
        stdout_a = "STDOUT NOT AVAILABLE IN DEBUG MODE"
      sys.stdout= saved_out
      stdout_e_stripped= self.__StringStrip(self.result_string.encode('UTF8'), isql=False)
      stdout_a_stripped= self.__StringStrip(stdout_a, isql=False)

      if stdout_a_stripped == stdout_e_stripped:
        return True

      else:
        self.__AnnotateDiff("python",
                            self.result_string,
                            stdout_a,
                            stdout_e_stripped,
                            stdout_a_stripped)
          

  def __PythonDataPrinter(self,cur):
    # Print a header.
    for fieldDesc in cur.description:
        print fieldDesc[kdb.DESCRIPTION_NAME].ljust(fieldDesc[kdb.DESCRIPTION_DISPLAY_SIZE]) ,
    print
    for fieldDesc in cur.description:
        print "-" * max((len(fieldDesc[kdb.DESCRIPTION_NAME]),fieldDesc[kdb.DESCRIPTION_DISPLAY_SIZE])),
    print

    # For each row, print the value of each field left-justified within
    # the maximum possible width of that field.
    fieldIndices = range(len(cur.description))
    for row in cur:
        for fieldIndex in fieldIndices:
            fieldValue = str(row[fieldIndex])
            fieldMaxWidth = max((len(cur.description[fieldIndex][kdb.DESCRIPTION_NAME]),cur.description[fieldIndex][kdb.DESCRIPTION_DISPLAY_SIZE]))

            print fieldValue.ljust(fieldMaxWidth) ,

        print
        
  def __ExtractDatabaseInfoCounts(self,buf):
    # Extract a raw binary sequence of (unsigned short, signed int) pairs into
    # a corresponding Python list of tuples.
    uShortSize = struct.calcsize('H')
    intSize = struct.calcsize('i')
    pairSize = uShortSize + intSize
    pairCount = len(buf) / pairSize

    pairs = []
    for i in range(pairCount):
        bufForThisPair = buf[i*pairSize:(i+1)*pairSize]
        relationId = struct.unpack('H', bufForThisPair[           : uShortSize])[0]
        count      = struct.unpack('i', bufForThisPair[uShortSize :           ])[0]
        pairs.append( (relationId, count) )
    return pairs

  def __GetDatabaseInfo(self, con, infoItems):
    Result = dict()
    for infoItem in infoItems:
        if infoItem in [kdb.isc_info_allocation,kdb.isc_info_no_reserve,isc_info_db_sql_dialect,kdb.isc_info_ods_minor_version,kdb.isc_info_ods_version,
                        kdb.isc_info_page_size,kdb.isc_info_current_memory,kdb.isc_info_forced_writes,kdb.isc_info_max_memory,kdb.isc_info_num_buffers,
                        kdb.isc_info_sweep_interval,kdb.isc_info_limbo,kdb.isc_info_attachment_id,kdb.isc_info_fetches,kdb.isc_info_marks,kdb.isc_info_reads,
                        kdb.isc_info_writes,isc_info_oldest_transaction,isc_info_oldest_active,isc_info_oldest_snapshot,isc_info_next_transaction,
                        isc_info_set_page_buffers,isc_info_db_read_only,isc_info_db_size_in_pages,isc_info_page_errors,isc_info_record_errors,
                        isc_info_bpage_errors,isc_info_dpage_errors,isc_info_ipage_errors,isc_info_ppage_errors,isc_info_tpage_errors]:
            intResult = con.database_info(infoItem,"i")
            Result[infoItem] = intResult
        elif infoItem == kdb.isc_info_base_level:
            strResult = con.database_info(infoItem,"s")
            Result[infoItem] = (struct.unpack("B",strResult[0])[0],struct.unpack("B",strResult[1])[0])
        elif infoItem == kdb.isc_info_db_id:
            strResult = con.database_info(infoItem,"s")
            intNameLen = struct.unpack("B",strResult[1])[0]
            intSiteLen = struct.unpack("B",strResult[2+intNameLen])[0]
            Result[infoItem] = (struct.unpack("B",strResult[0])[0],strResult[2:2+intNameLen],strResult[3+intNameLen:3+intNameLen+intSiteLen])
        elif infoItem == kdb.isc_info_implementation:
            strResult = con.database_info(infoItem,"s")
            Result[infoItem] = (struct.unpack("B",strResult[1])[0],struct.unpack("B",strResult[2])[0])
        elif infoItem in [kdb.isc_info_version,isc_info_firebird_version]:
            strResult = con.database_info(infoItem,"s")
            intStrLen = struct.unpack("B",strResult[1])[0]
            Result[infoItem] = (struct.unpack("B",strResult[0])[0],strResult[2:2+intStrLen])
        elif infoItem == kdb.isc_info_user_names:
            strResult = con.database_info(infoItem,"s")
            pos = 0
            userNames = list()
            while pos < len(strResult):
                nameLen = struct.unpack("B",strResult[pos])[0]
                pos = pos + 1
                userNames.append(strResult[pos:pos+nameLen])
                pos = pos + nameLen + 1
            Result[infoItem] = userNames
        elif infoItem in [kdb.isc_info_backout_count,kdb.isc_info_delete_count,kdb.isc_info_expunge_count,kdb.isc_info_insert_count,
                          kdb.isc_info_purge_count,kdb.isc_info_read_idx_count,kdb.isc_info_read_seq_count,kdb.isc_info_update_count]:
            binResult = con.database_info(infoItem,"s")
            Result[infoItem] = self.__ExtractDatabaseInfoCounts(binResult)
    return Result

  def __MakeNamespaces(self):
    global_ns={"context"           : self.__context,
               "kdb"               : kdb,
               "printData"         : self.__PythonDataPrinter,
               "getDatabaseInfo"   : self.__GetDatabaseInfo,
               "sys"               : sys,
               "dsn"               : self.__dsn,
               "user_name"         : self.user_name,
               "user_password"     : self.user_password,
               "page_size"         : self.page_size,
               "sql_dialect"       : self.sql_dialect,
               "character_set"     : self.character_set,
               "db_path_property"  : self.db_path_property,
#               "server_location"   : context["server_location"],
#               "database_location" : context[self.db_path_property],
               "db_conn"           : self.__db_conn}

    local_ns={}

    return global_ns, local_ns


  def __DropDatabase(self):
    try:
      if not self.__db_conn:
        self.__db_conn= self.__KConnectDB()
      self.__db_conn.drop_database()
    except:
      if self.__result.GetOutcome() == self.__result.PASS: # if the test has passed so far
        # then mark it as ERROR.  otherwise just annotate the database path so as to
        # leave the original result intact
        self.__result.NoteException(cause="Exception raised while dropping database.  " + \
                                          "Ensure database is removed as subsequent tests may fail.")
      self.__result["FirebirdTest.db_unable_to_remove"]= self.__dsn
        
    else:
      return True
      
  def __CleanUp(self, drop=True):
    errors=[]
    
    for fname in self.__clean_up:
      if os.access(fname, os.F_OK):
        try:
          os.remove(fname)
        except:
          errors.append(fname)
          
    if self.drop_db == "true" and drop:
      self.__DropDatabase()
      
    if errors:
      self.__result["FirebirdTest.temp_files_unable_to_remove"]= string.join(errors, ", ")

  def Run(self, context, result):
    # database connection placeholder
    self.__db_conn = None

    # qm will generate errors if these are missing:
    context["temp_directory"]
    context["server_location"]
    
    causes=[]
    if not os.access(context["temp_directory"], os.W_OK):
      causes.append("Temporary directory given in context is not writeable")
        
    # universally required fields:
    
    if not self.user_name:
      causes.append("No user name supplied for database")
      
    if not self.user_password:
      causes.append("No password specified for database")
      
    if not self.db_name:
      causes.append("No database specified")
      
    if not self.db_path_property:
      causes.append("No database path property specified")
      
    # we need to exit now if there are any errors, because we need
    # these values to build strings like DSN and DB path which in
    # turn need to be tested
    
    if causes:
      result.SetOutcome(result.ERROR, string.join(causes, ", ") + ".")
      return
      
    # let qm do the work:
    context[self.db_path_property]
        
    # users leaving off the trailing path delimiter from directory
    # names in the context file will lead to databases being created
    # in the wrong directory.  this has the potential to wreak some
    # havok regarding security, etc.
    
    if context["server_location"] in ["127.0.0.1", "localhost"]:
      if context[self.db_path_property][-1] != os.sep:
        context[self.db_path_property] += os.sep
        
      if context["temp_directory"][-1] != os.sep:
        context["temp_directory"] += os.sep
        
    self.__db_path= context[self.db_path_property] + self.db_name
    
    # check for prerequisities to restore from backup
    if self.create_db_method == "Restore From Backup":
      
      context["gbak_path"]
      
      if not self.backup_file_path:
        causes.append("No backup file specified")            
      elif not os.access(self.backup_file_path, os.F_OK):
        causes.append("Backup file <i>%s</i> does not exist" % self.backup_file_path)
      if not os.access(context["gbak_path"], os.F_OK):
        causes.append("GBAK path given in context does not exist")
      elif not os.access(context["gbak_path"], os.X_OK):
        causes.append("GBAK path given in context is not executable")
      if os.access(self.__db_path, os.F_OK):
        causes.append("Database <i>%s</i> already exists" % self.__db_path)
      
    # check for prerequisities to run isql scripts
    if self.isql_script or self.statement_type_and_result == "SQL: String":
      if not os.access(context["isql_path"], os.F_OK):
        causes.append("ISQL path given in context does not exist")
      elif not os.access(context["isql_path"], os.X_OK):
        causes.append("ISQL path given in context is not executable")
        
    # check for prerequisities to populate table from tuple
    if self.insert_statement or self.data_tuple:

      if self.data_tuple:
        try:
          insert_tuple= eval(self.data_tuple)
        except:
          result.NoteException(cause="Exception raised while evaluating data tuple.")
          return
        else:
          if type(insert_tuple) not in [tuple, list]:
            causes.append("Invalid data tuple given (must be tuple of tuples)")
          else:
            self.data_tuple= insert_tuple
      else:
        causes.append("No data tuple given")
        
      if not self.insert_statement:
        causes.append("No SQL insert statement given")
     
    # check for prerequisities to run actual test
    if self.statement_type_and_result in ["Python: True" or "Python: False"]:
      if not self.test_expr:
        causes.append("No Python test expression given for statement type 'Python'")
        
    elif self.statement_type_and_result == "SQL: String":
      if self.test_expr:
        causes.append("Python test expression not applicable for statement type 'SQL'")
        result["FirebirdTest.python_test_expr"]= self.test_expr
        
    elif self.statement_type_and_result == "Python: String":
      if not (self.test_expr or self.source_code):
        causes.append("Either source code or test expression required for statement type 'Python'")

    else:
      if self.test_expr:
        causes.append("Python test expression not applicable for statement type 'None'")
        result["FirebirdTest.python_test_expr"]= self.test_expr
        
      if self.source_code:
        causes.append("Source code not applicable for statement type 'None'")
        result["FirebirdTest.source_code"]= self.source_code
        
      if self.result_string:
        causes.append("Result string not applicable for statement type 'None'")
        result["FirebirdTest.result_string"]= self.result_string
        
      if self.substitutions:
        causes.append("Substitutions not applicable for statement type 'None'")
    
    if causes:
      result.SetOutcome(result.ERROR, string.join(causes, ",  ") + ".")
      return
    # done with sanity checks, now put together attributes we're
    # going to use later
    
    if context["server_location"][-1] != ":":
      context["server_location"] += ":"
    
    if context["server_location"][-1] != ":":
      context["server_location"] += ":"
      
    self.__dsn= "".join([context["server_location"],
                        context[self.db_path_property],
                        self.db_name])
                        
    self.__isqlsubs= map(re.compile,
                         ["(?m)Database:.*$", "SQL>\s*", "CON>\s*", "-->\s*"])
                       
    self.__result = result
    self.__context= context
    
    # # # # # # # # # # # # # # # # # # # # # # # #
    self.__clean_up= []
    
    if self.create_db_method == "Restore From Backup":
      if self.drop_db:
        self.__clean_up.append(self.__db_path)
        
      retval= self.__RestoreBackup()
      
      if retval:
        self.__clean_up= []
      else:
        self.__CleanUp()
        return
    else:
      self.__KCreateDB()

    if self.isql_script :
      retval= self.__ExecISQLCommandsBlind()

      if not retval:
        self.__CleanUp()
        return

    if self.insert_statement:
      self.__db_conn= self.__KConnectDB()
      if not self.__db_conn:
        return
      retval= self.__InsertParam()

      if not retval:
        self.__CleanUp()
        return

    if self.statement_type_and_result in ["Python: True", "Python: False"]:
      if (not self.__db_conn) and (self.create_db_method != "None"):
        self.__db_conn= self.__KConnectDB()
        if not self.__db_conn:
          return
      retval= self.__ExecPythonBool()

      if not retval:
        self.__CleanUp()
        return

    elif self.statement_type_and_result == "Python: String":
      if (not self.__db_conn) and (self.create_db_method != "None"):
        self.__db_conn= self.__KConnectDB()
        if not self.__db_conn:
          return
      retval= self.__ExecPython()

      if not retval:
        self.__CleanUp()
        return

    elif self.statement_type_and_result == "SQL: String":
      retval= self.__ExecISQLCommands()

      if not retval:
        self.__CleanUp()
        return
        
    if self.drop_db == "true":
      retval= self.__DropDatabase()
      
      self.__CleanUp(drop=False)
      
def _colorizePython(s):
    # If the colorizing module is not available, just skip colorizing.
    if hermann_colorize is None:
        return _PRE_NO_MARGIN % s

    stream = StringIO()
    p = hermann_colorize.Parser(s, out=stream)
    p.format(None, None)
    colorized = stream.getvalue()
    return colorized


