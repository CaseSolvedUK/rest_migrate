// Copyright (c) 2021, CaseSolved and contributors
// For license information, please see license.txt

frappe.ui.form.on('REST Integration Map', {
	setup: function(frm) {
		frm.set_query('data_field', (doc, dt, dn) => {
			if (doc.is_group) {
				return {filters: {is_group: 0}};
			} else {
				return {filters: {parent_segment: doc.parent_segment, is_group: 0}};
			}
		});
		frm.set_query('target_df', (doc, dt, dn) => {
			return {
				query: "rest_migrate.rest_migrate.doctype.rest_integration_map.rest_integration_map.df_list",
				filters: {parent: doc.target_dt || '', fieldtype: ['NOT LIKE', '%Break%']},
			}
		});
	},
});
