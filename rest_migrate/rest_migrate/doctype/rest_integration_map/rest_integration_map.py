# -*- coding: utf-8 -*-
# Copyright (c) 2021, CaseSolved and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import sys
import frappe
import requests
import json
from urllib.parse import urlparse, urlencode
from frappe import _
from frappe.realtime import publish_progress
from frappe.utils.nestedset import NestedSet


#TODO: Link docs related by related records

# NOTES:
# Target dt & df can be blank in case a related query uses the data, e.g. an external user_id is referenced by a child table
# If the data is in a dict, the parent segment_name will be used as the key to access the data which should be a list of records
# An exception during import appears to cause a db rollback, which is good for trial and error testing

class RESTIntegrationMap(NestedSet):
	def before_save(self):
		"Controller event"
		self.segment_name = self.segment_name.strip('{}\/')
		if not self.target_dt or not self.target_df:
			self.target_dt = self.target_df = None

	def on_change(self):
		"Controller event"
		self.update_root_attrs()

	def on_trash(self):
		"Controller event: override to allow root deletion"
		self.validate_if_child_exists()

	def update_root_attrs(self):
		"Copies attributes from the root segment to its children"
		root_attrs = ['keep_existing']
		for item in frappe.get_all('REST Integration Map'):
			doc = frappe.get_cached_doc('REST Integration Map', item.name)
			dirty = False
			for field in root_attrs:
				root_value = doc.get_root_value(field)
				if root_value != getattr(doc, field):
					setattr(doc, field, root_value)
					dirty = True
			if dirty:
				doc.save()

	def add_url_segment(self, urls, credentials):
		"Prepends the segment to the existing urls"
		if self.data_field:
			ref_field = frappe.get_cached_doc('REST Integration Map', self.data_field)
			segs = list(set([record[ref_field.segment_name] for record in ref_field.get_all(credentials)]))
		else:
			segs = [self.segment_name]

		new_urls = []
		for seg in segs:
			if urls:
				for url in urls:
					new_urls += [seg + url] if url.startswith('?') else [seg + '/' + url]
			else:
				new_urls += [seg]

		return new_urls

	def get_urls(self, credentials):
		"Compiles the API urls"
		if hasattr(self, '_urls'):
			return self._urls

		parent_segment = self.parent_segment
		if self.is_group:
			urls = self.add_url_segment([], credentials)
		else:
			q = self.get_url_query()
			urls = ['?' + q] if q else []

		while parent_segment:
			parent = frappe.get_cached_doc('REST Integration Map', parent_segment)
			parent_segment = parent.parent_segment
			urls = parent.add_url_segment(urls, credentials)

		self._urls = urls
		return urls

	def get_url_query(self):
		"URL-specific parameters"
		d = {p.key: p.value for p in self.get_params() if p.type == 'URL Query'}
		return urlencode(d)

	def get_header_params(self):
		"URL-specific parameters"
		return {p.key: p.value for p in self.get_params() if p.type == 'Header'}

	def get_params(self):
		"""Merge request parameters set anywhere on the url branch
		Note that duplicate parameter key:values will be overwritten and not appended"""
		if not self.parent_segment:
			return self.params
		parent = self.parent_segment
		params = []
		while parent:
			pdoc = frappe.get_cached_doc('REST Integration Map', parent)
			params += pdoc.params
			parent = pdoc.parent_segment
		return params

	def get_root_value(self, param):
		"Get keep_existing which is set on the root"
		value = getattr(self, param)
		parent_segment = self.parent_segment
		while parent_segment:
			value, parent_segment = frappe.get_value('REST Integration Map', parent_segment, [param, 'parent_segment'])
		return value

	def get_all(self, credentials):
		"Return the results from the API"
		if self.is_group:
			frappe.throw(_('Please run get_all on a data field and not a URL segment'))

		urls = self.get_urls(credentials)
		dict_key = frappe.get_value('REST Integration Map', self.parent_segment, 'segment_name')
		results = []
		session = None
		headers = self.get_header_params()
		headers.update({'Accept': 'application/json'})
		for url in urls:
			if session:
				r = session.get(url)
			else:
				session = requests.Session()
				session.headers = headers
				if credentials:
					if credentials['auth'].startswith('Basic'):
						session.auth = requests.auth.HTTPBasicAuth(credentials['username'], credentials['password'])
					elif credentials['auth'].startswith('Digest'):
						session.auth = requests.auth.HTTPDigestAuth(credentials['username'], credentials['password'])
					else:
						frappe.throw(f'Unsupported authentication type: {credentials["auth"]}')
					r = session.get(url)
				else:
					r = session.get(url)
					if r.status_code == 401:
						if r.headers['WWW-Authenticate'].startswith('OAuth'):
							hostname = getattr(urlparse(url), 'hostname')
							apps = frappe.get_list('Connected App', filters={'provider_name': hostname}, as_list=True)
							if apps:
								connected_app = frappe.get_doc('Connected App', apps[0][0])
							else:
								frappe.throw(f'Provider {hostname} not configured for OAuth in Connected Apps')
							session.close()
							session = connected_app.get_oauth2_session()
							session.headers.update(headers)
							r = session.get(url)
						else:
							#Let the js client code request credentials from the user
							session.close()
							frappe.throw(r.headers['WWW-Authenticate'], exc=frappe.PermissionError)

			r.raise_for_status()
			content = r.headers['content-type'].lower()
			if 'json' in content:
				result = r.json()
				if isinstance(result, dict):
					results += result[dict_key]
				else:
					results += result
			else:
				session.close()
				frappe.throw(f'Unknown content type: {content}')
		session.close()
		return results

	def print_all(self):
		print(json.dumps(self.get_all({}), indent=2))


def get_func(mstr):
	"Either outputs a string method to operate on the field object like '.lower()' or a callable"
	if mstr.startswith('.'):
		return mstr[1:]
	module, _dummy, function = mstr.rpartition('.')
	if module:
		try:
			mod = globals()['__builtins__'][module]
		except KeyError:
			__import__(module)
			mod = sys.modules[module]
	else:
		return globals()['__builtins__'][function]
	return getattr(mod, function)

@frappe.whitelist()
def import_data(doc=None, name=None, credentials={}):
	"Import all API data to the mapped fields. Can be called from the doc form or treeview with different args"
	if isinstance(doc, str):
		doc = json.loads(doc)
		name = doc['name']
	doc = frappe.get_cached_doc('REST Integration Map', name)
	if doc.is_group:
		frappe.throw(_('Import is only valid on a data field'))
	mapping = frappe.get_all('REST Integration Map',
				fields=('segment_name as source_df', 'target_dt', 'target_df', 'convert_method', 'data_field'),
				filters={'parent_segment': doc.parent_segment})
	dts = []
	source_keys = []
	for m in mapping:
		if m['convert_method']:
			m['method'] = get_func(m['convert_method'])
		if m['target_df']:
			m['df'], m['dft'] = frappe.get_value('DocField', m['target_df'], ['fieldname', 'fieldtype'])
			dts += [m['target_dt']]
		m['source_key'], _dummy, m['source_df'] = m['source_df'].rpartition('.')
		source_keys += [m['source_key']]
		if m['data_field']:
			m['ref_source_key'], _dummy, m['ref_source_df'] = frappe.get_value('REST Integration Map',
				m['data_field'], 'segment_name').rpartition('.')

	dts = [dt for dt in set(dts) if dt]
	source_keys = list(set(source_keys))
	data = doc.get_all(credentials)
	keep_existing = doc.get_root_value('keep_existing')
	publish_progress(0.0)
	for i, record in enumerate(data, 1):
		new_docs = []
		for dt in dts:
			for skey in source_keys:
				if skey:
					subrecords = record[skey]
				else:
					subrecords = [record]
				for subrecord in subrecords:
					new_doc = {}
					for m in mapping:
						if m['target_dt'] == dt and m['source_key'] == skey:
							if m['source_df'] in subrecord:
								src = subrecord[m['source_df']]
							elif 'ref_source_df' in m and m['ref_source_key'] in ('', skey):
								if m['ref_source_key']:
									src = subrecord[m['ref_source_df']]
								else:
									src = record[m['ref_source_df']]
							else:
								continue

							if 'method' in m:
								if isinstance(m['method'], str):
									val = getattr(src, m['method'])()
								else:
									val = m['method'](src)
							else:
								val = default_conversion(src, m['dft'])

							if val != '':
								new_doc[m['df']] = val
								new_doc['doctype'] = dt
					if new_doc:
						new_docs += [new_doc]
		insert_and_link(new_docs, keep_existing, (i*100.0)/len(data))
	frappe.db.commit()
	return 'Success'

@frappe.whitelist()
def get_data(doc=None, name=None, credentials={}):
	if isinstance(doc, str):
		doc = json.loads(doc)
		name = doc['name']
	d = frappe.get_cached_doc('REST Integration Map', name)
	return d.get_all(credentials)
	

def insert_and_link(new_docs, keep_existing, percentage):
	parents = []
	children = []
	for new_doc in new_docs:
		d = frappe.get_doc(new_doc)
		publish_progress(percentage, doctype=d.doctype, docname=d.name)
		try:
			d.insert()
			parents += [d]
			frappe.msgprint(f"{d.doctype} {d.name} created", title=_("Parent"), indicator="green")
		except frappe.DuplicateEntryError:
			# Mandatory validation happens before insert and duplicate entry error
			org_doc = frappe.get_doc(d.doctype, d.name)
			parents += [org_doc]
			if not keep_existing:
				org_doc.update(new_doc)
				org_doc.save()
		except frappe.MandatoryError as e:
			if 'parent' in str(e):
				children += [d]
			else:
				frappe.msgprint(f"{repr(e)}", title=_("MandatoryError"), indicator="red")
		except frappe.LinkValidationError as e:
			frappe.msgprint(f"{repr(e)}", title=_("LinkValidationError"), indicator="red")

	for child in children:
		orphan = True
		for parent in parents:
			fieldname = parent.get_parentfield_of_doctype(child.doctype)
			if fieldname:
				orphan = False
				child.parent = parent.name
				child.parenttype = parent.doctype
				child.parentfield = fieldname
				parent.append(fieldname, child)
				parent.save()
				frappe.msgprint(f"{child.doctype} {child.name} attached to {parent.doctype} {parent.name}",
					title=_("Child"), indicator="green")
				break
		if orphan:
			frappe.msgprint(f"{child.doctype} orphan lost", title=_("Child"), indicator="red")

def default_conversion(src, fieldtype):
	"Cast the imported data to the correct type for the destination"
	if isinstance(src, list):
		src = '\n'.join(src)
	if isinstance(src, dict):
		src = json.dumps(src)

	dest = frappe.utils.cast_fieldtype(fieldtype, src)
	if dest != src:
		return dest

	if fieldtype in ['Attach', 'Attach Image', 'Image']:
		dest=str(src)
	elif fieldtype in ['Check']:
		dest=int(bool(src))
	elif fieldtype in ['Currency', 'Float', 'Percent']:
		dest=float(src)
	elif fieldtype in ['Duration', 'Time']:
		dest=frappe.utils.to_timedelta(src)
	elif fieldtype in ['Int', 'Rating']:
		dest=int(src)
	elif fieldtype in ['Fold', 'Geolocation', 'Password', 'Signature']:
		frappe.throw(f'{dest_type} ' + _('not supported'))
	else:
		# There are a lot of string types
		dest = str(src)

	return dest

#@frappe.whitelist()
def import_openapi_yaml(file):
	#TODO
	pass

def import_fixture(data):
	"Import REST APIs as json overwriting existing"
	#TODO
	pass

def export_fixture():
	"Export REST APIs as json"
	#TODO
	pass

_root_name = _('REST APIs')
@frappe.whitelist()
def get_children(doctype, parent=None, is_root=None):
	"Treeview method"
	if parent is None and is_root is None:
		# the root UI node
		return [{'value': _root_name}]
	elif is_root == 'true':
		# the root DB nodes
		parent = ''

	fields = ['name as value', 'segment_name as label', 'is_group as expandable']
	filters = {
		'parent_segment': ('=', parent),
	}

	return frappe.get_list(doctype, fields=fields, filters=filters, order_by='segment_name')

@frappe.whitelist()
def add_node(doctype, segment_name, is_group, parent, is_root):
	"Treeview method"
	if parent == _root_name:
		parent = ''
	frappe.get_doc({
		'doctype': doctype,
		'segment_name': segment_name,
		'parent_segment': parent,
		'is_group': is_group,
	}).insert()

@frappe.whitelist()
def df_list(doctype, txt, searchfield, start, page_length, filters, as_dict):
	"DocField select list helper"
	as_list = not as_dict
	return frappe.get_list(doctype, fields=('name', 'label', 'fieldtype'), filters=filters, as_list=as_list)
