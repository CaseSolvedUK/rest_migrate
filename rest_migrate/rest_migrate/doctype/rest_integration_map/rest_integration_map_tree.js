function handle_credentials(r, cb) {
	if (r.exc_type === 'PermissionError') {
		if (r.exc.includes('Basic') || r.exc.includes('Digest')) {
			frappe.prompt([
				{
					label: 'Username',
					fieldname: 'username',
					fieldtype: 'Data'
				},
				{
					label: 'Password',
					fieldname: 'password',
					fieldtype: 'Password'
				},
			], (values) => {
				if (values.username) {
					const credentials = Object.assign({auth: r.exc}, values);
					cb(credentials);
				} else {
					frappe.throw(__('Please provide credentials'));
				}
			});
		} else {
			frappe.throw(__(`Unsupported authentication type: ${r.exc}`));
		}
	} else if (!r.exc) {
		frappe.throw(__('Server error'));
	} else {
		frappe.throw(r.exc);
	}
}

frappe.treeview_settings['REST Integration Map'] = {
	breadcrumb: "REST Migrate",
	get_tree_nodes: "rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.get_children",
	add_tree_node: "rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.add_node",
	get_label: function(node) {
		if (node.data.label) {
			return node.data.label;
		}
		return node.label;
	},
	fields:[
		{fieldtype:'Data', fieldname: 'segment_name',
			label:__('New Segment Name'), reqd: true, description: __('URL segment (no leading or trailing slashes) or field name')},
		{fieldtype:'Check', fieldname:'is_group', label:__('Is URL Path Segment'),
			description: __("Is a URL segment or API field name")}
	],
	toolbar: [
		{
			label: __('API Import'),
			condition: function(node) {
				return !node.expandable;
			},
			click: function(node) {
				frappe.call({
					method: 'rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.import_data',
					args: {name: node.label},
					error: function(r) {
						handle_credentials(r, (credentials) => {
							frappe.call({
								method: 'rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.import_data',
								args: {name: node.label, credentials: credentials}
							});
						});
					}
				});
			},
			btnClass: "hidden-xs"
		},
		{
			label: __('Show Data'),
			condition: function(node) {
				return !node.expandable;
			},
			click: function(node) {
				frappe.call({
					method: 'rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.get_data',
					args: {name: node.label},
					callback: function(r) {frappe.msgprint({title: __('Show Data'), indicator: 'green', message: JSON.stringify(r.message,null,2)})},
					error: function(r) {
						handle_credentials(r, (credentials) => {
							frappe.call({
								method: 'rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.get_data',
								args: {name: node.label, credentials: credentials},
								callback: function(r) {frappe.msgprint({title: __('Show Data'), indicator: 'green', message: JSON.stringify(r.message,null,2)})}
							});
						});
					}
				});
			},
			btnClass: "hidden-xs"
		},
	],
	extend_toolbar: true
}
