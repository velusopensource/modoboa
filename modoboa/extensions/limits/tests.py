from django.core.urlresolvers import reverse
from modoboa.lib.tests import ExtTestCase
from modoboa.lib import parameters
from modoboa.core.models import User
from modoboa.core.factories import UserFactory
from modoboa.extensions.admin.factories import (
    populate_database
)
from modoboa.extensions.admin.models import Alias, Domain
from modoboa.extensions.limits.models import LimitTemplates


class PermissionsTestCase(ExtTestCase):
    fixtures = ["initial_users.json"]

    def setUp(self):
        super(PermissionsTestCase, self).setUp()
        self.activate_extensions('limits')
        populate_database()

    def test_domainadmin_deletes_reseller(self):
        """Check if a domain admin can delete a reseller.

        Expected result: no.
        """
        values = dict(
            username="reseller@test.com", first_name="Reseller", last_name="",
            password1="toto", password2="toto", role="Resellers",
            is_active=True, email="reseller@test.com", stepid='step2'
        )
        self.ajax_post(reverse("admin:account_add"), values)
        account = User.objects.get(username="reseller@test.com")
        self.clt.logout()
        self.clt.login(username="admin@test.com", password="toto")
        resp = self.ajax_post(
            reverse("admin:account_delete", args=[account.id]),
            {}, status=403
        )
        self.assertEqual(resp, "Permission denied")


class ResourceTestCase(ExtTestCase):
    fixtures = ["initial_users.json"]

    def setUp(self):
        """Custom setUp method.

        The 'limits' is manually loaded to ensure extra parameters
        provided by 'postfix_relay_domains' are properly received.
        """
        super(ResourceTestCase, self).setUp()
        self.activate_extensions('limits')
        for tpl in LimitTemplates().templates:
            parameters.save_admin('DEFLT_%s' % tpl[0].upper(), 2, app='limits')
        populate_database()

    def _create_account(self, username, role='SimpleUsers', status=200):
        values = dict(
            username=username, first_name="Tester", last_name="Toto",
            password1="toto", password2="toto", role=role,
            quota_act=True,
            is_active=True, email=username, stepid='step2',
        )
        return self.ajax_post(
            reverse("admin:account_add"), values, status
        )

    def _create_alias(self, email, rcpt='user@test.com', status=200):
        values = dict(
            email=email, recipients=rcpt, enabled=True
        )
        return self.ajax_post(
            reverse("admin:alias_add"), values, status
        )

    def _create_domain(self, name, status=200, withtpl=False):
        values = {
            "name": name, "quota": 100, "create_dom_admin": "no",
            "create_aliases": "no", "stepid": 'step2'
        }
        if withtpl:
            values['create_dom_admin'] = 'yes'
            values['dom_admin_username'] = 'admin'
            values['create_aliases'] = 'yes'
        return self.ajax_post(
            reverse("admin:domain_add"), values, status
        )

    def _domain_alias_operation(self, optype, domain, name, status=200):
        dom = Domain.objects.get(name=domain)
        values = {
            'name': dom.name, 'quota': dom.quota, 'enabled': dom.enabled,
        }
        aliases = [alias.name for alias in dom.domainalias_set.all()]
        if optype == 'add':
            aliases.append(name)
        else:
            aliases.remove(name)
        for cpt, alias in enumerate(aliases):
            fname = 'aliases' if not cpt else 'aliases_%d' % cpt
            values[fname] = alias
        self.ajax_post(
            reverse("admin:domain_change", args=[dom.id]),
            values, status
        )

    def _check_limit(self, name, curvalue, maxvalue):
        l = self.user.limitspool.get_limit('%s_limit' % name)
        self.assertEqual(l.curvalue, curvalue)
        self.assertEqual(l.maxvalue, maxvalue)


class DomainAdminTestCase(ResourceTestCase):

    def setUp(self):
        super(DomainAdminTestCase, self).setUp()
        self.user = User.objects.get(username='admin@test.com')
        self.user.limitspool.set_maxvalue('mailboxes_limit', 2)
        self.user.limitspool.set_maxvalue('mailbox_aliases_limit', 2)
        self.clt.logout()
        self.clt.login(username='admin@test.com', password='toto')

    def test_mailboxes_limit(self):
        self._create_account('tester1@test.com')
        self._check_limit('mailboxes', 1, 2)
        self._create_account('tester2@test.com')
        self._check_limit('mailboxes', 2, 2)
        resp = self._create_account('tester3@test.com', status=403)
        self._check_limit('mailboxes', 2, 2)
        self.ajax_post(
            reverse('admin:account_delete',
                    args=[User.objects.get(username='tester2@test.com').id]),
            {}
        )
        self._check_limit('mailboxes', 1, 2)

    def test_aliases_limit(self):
        self._create_alias('alias1@test.com')
        self._check_limit('mailbox_aliases', 1, 2)
        self._create_alias('alias2@test.com')
        self._check_limit('mailbox_aliases', 2, 2)
        resp = self._create_alias('alias3@test.com', status=403)
        self._check_limit('mailbox_aliases', 2, 2)
        self.ajax_post(
            reverse('admin:alias_delete') + '?selection=%d' \
                % Alias.objects.get(address='alias2', domain__name='test.com').id,
            {}
        )
        self._check_limit('mailbox_aliases', 1, 2)

    def test_aliases_limit_through_account_form(self):
        user = User.objects.get(username='user@test.com')
        values = dict(
            username=user.username, role=user.group,
            is_active=user.is_active, email=user.email, quota_act=True,
            aliases="alias1@test.com", aliases_1="alias2@test.com"
        )
        self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values
        )
        Alias.objects.get(address='alias1', domain__name='test.com')
        self._check_limit('mailbox_aliases', 2, 2)


class ResellerTestCase(ResourceTestCase):

    def setUp(self):
        super(ResellerTestCase, self).setUp()
        self.user = UserFactory.create(
            username='reseller', groups=('Resellers',)
        )
        self.clt.logout()
        self.clt.login(username='reseller', password='toto')

    def test_domains_limit(self):
        self._create_domain('domain1.tld')
        self._check_limit('domains', 1, 2)
        self._create_domain('domain2.tld')
        self._check_limit('domains', 2, 2)
        resp = self._create_domain('domain3.tld', 403)
        self._check_limit('domains', 2, 2)
        self.ajax_post(
            reverse('admin:domain_delete',
                    args=[Domain.objects.get(name='domain2.tld').id]),
            {}
        )
        self._check_limit('domains', 1, 2)

    def test_domain_aliases_limit(self):
        self._create_domain('pouet.com')
        self._domain_alias_operation('add', 'pouet.com', 'domain_alias1.tld')
        self._check_limit('domain_aliases', 1, 2)
        self._domain_alias_operation('add', 'pouet.com', 'domain_alias2.tld')
        self._check_limit('domain_aliases', 2, 2)
        resp = self._domain_alias_operation(
            'add', 'pouet.com', 'domain_alias3.tld', 403
        )
        self._check_limit('domain_aliases', 2, 2)
        self._domain_alias_operation('delete', 'pouet.com', 'domain_alias2.tld')
        self._check_limit('domain_aliases', 1, 2)

    def test_domain_admins_limit(self):
        self._create_domain('domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        self._check_limit('domain_admins', 1, 2)
        self._create_account('admin2@domain.tld', role='DomainAdmins')
        self._check_limit('domain_admins', 2, 2)
        resp = self._create_account('admin3@domain.tld', role='DomainAdmins', status=400)
        self.assertEqual(
            resp['form_errors']['role'][0],
            'Select a valid choice. DomainAdmins is not one of the available choices.'
        )
        self._check_limit('domain_admins', 2, 2)

        self.user.limitspool.set_maxvalue('mailboxes_limit', 3)
        self._create_account('user1@domain.tld')
        user = User.objects.get(username='user1@domain.tld')
        values = {
            'username': user.username, 'role': 'DomainAdmins',
            'quota_act': True, 'is_active': user.is_active,
            'email': user.email
        }
        resp = self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values, status=400
        )
        self.assertEqual(
            resp['form_errors']['role'][0],
            'Select a valid choice. DomainAdmins is not one of the available choices.'
        )
        self._check_limit('domain_admins', 2, 2)

    def test_domain_admin_resource_are_empty(self):
        self._create_domain('domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        domadmin = User.objects.get(username='admin1@domain.tld')
        for l in ['mailboxes', 'mailbox_aliases']:
            self.assertEqual(
                domadmin.limitspool.get_limit('%s_limit' % l).maxvalue, 0
            )

    def test_domain_admins_limit_from_domain_tpl(self):
        self.user.limitspool.set_maxvalue('domains_limit', 3)
        self._create_domain('domain1.tld', withtpl=True)
        self._create_domain('domain2.tld', withtpl=True)
        self._check_limit('domain_admins', 2, 2)
        self._check_limit('domains', 2, 3)
        resp = self._create_domain('domain3.tld', status=200, withtpl=True)
        self._check_limit('domain_admins', 2, 2)
        self._check_limit('domains', 3, 3)

    def test_reseller_deletes_domain(self):
        """Check if all resources are restored after the deletion.
        """
        self._create_domain('domain.tld', withtpl=True)
        dom = Domain.objects.get(name="domain.tld")
        self.ajax_post(
            reverse("admin:domain_delete", args=[dom.id]),
            {}
        )
        self._check_limit('domains', 0, 2)
        self._check_limit('domain_admins', 1, 2)
        self._check_limit('mailboxes', 0, 2)
        self._check_limit('mailbox_aliases', 0, 2)

    def test_sadmin_removes_ownership(self):
        self._create_domain('domain.tld', withtpl=True)
        dom = Domain.objects.get(name="domain.tld")
        self.clt.logout()
        self.clt.login(username='admin', password='password')
        self.ajax_get(
            "{0}?domid={1}&daid={2}".format(
                reverse('admin:permission_remove'), dom.id, self.user.id
            ), {}
        )
        self._check_limit('domains', 0, 2)
        self._check_limit('domain_admins', 0, 2)
        self._check_limit('mailboxes', 0, 2)
        self._check_limit('mailbox_aliases', 0, 2)

    def test_allocate_from_pool(self):
        self._create_domain('domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        user = User.objects.get(username='admin1@domain.tld')

        # Give 1 mailbox and 2 aliases to the admin -> should work
        values = {
            'username': user.username, 'role': user.group, 'quota_act': True,
            'is_active': user.is_active, 'email': user.email,
            'mailboxes_limit': 1, 'mailbox_aliases_limit': 2
        }
        self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values
        )
        self._check_limit('mailboxes', 1, 1)
        self._check_limit('mailbox_aliases', 0, 0)

        # Delete the admin -> resources should go back to the
        # reseller's pool
        self.ajax_post(
            reverse("admin:account_delete", args=[user.id]),
            {}
        )
        self._check_limit('mailboxes', 0, 2)
        self._check_limit('mailbox_aliases', 0, 2)

    def test_restore_resources(self):
        self._create_domain('domain.tld')
        dom = Domain.objects.get(name='domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        user = User.objects.get(username='admin1@domain.tld')
        values = {
            'username': user.username, 'role': user.group, 'quota_act': True,
            'is_active': user.is_active, 'email': user.email,
            'mailboxes_limit': 1, 'mailbox_aliases_limit': 2
        }
        self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values
        )
        dom.add_admin(user)
        self.clt.logout()
        self.clt.login(username='admin1@domain.tld', password='toto')
        self._create_account('user1@domain.tld')
        self._create_alias('alias1@domain.tld', 'user1@domain.tld')
        self._create_alias('alias2@domain.tld', 'user1@domain.tld')
        self.clt.logout()
        self.clt.login(username='reseller', password='toto')
        # Delete the admin -> resources should go back to the
        # reseller's pool
        self.ajax_post(
            reverse("admin:account_delete", args=[user.id]),
            {}
        )
        self._check_limit('mailboxes', 1, 2)
        self._check_limit('mailbox_aliases', 2, 2)

    def test_change_role(self):
        self._create_domain('domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        user = User.objects.get(username='admin1@domain.tld')

        # Give 1 mailbox and 2 aliases to the admin -> should work
        values = {
            'username': user.username, 'role': user.group, 'quota_act': True,
            'is_active': user.is_active, 'email': user.email,
            'mailboxes_limit': 1, 'mailbox_aliases_limit': 2
        }
        self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values
        )
        self._check_limit('mailboxes', 1, 1)
        self._check_limit('mailbox_aliases', 0, 0)

        # Change admin role to SimpleUser -> resources should go back
        # to the reseller.
        values = {
            'username': user.username, 'role': 'SimpleUsers', 'quota_act': True,
            'is_active': user.is_active, 'email': user.email,
        }
        self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values
        )
        self._check_limit('mailboxes', 1, 2)
        self._check_limit('mailbox_aliases', 0, 2)

    def test_allocate_too_much(self):
        self._create_domain('domain.tld')
        self._create_account('admin1@domain.tld', role='DomainAdmins')
        user = User.objects.get(username='admin1@domain.tld')

        # Give 2 mailboxes and 3 aliases to the admin -> should fail.
        values = {
            'username': user.username, 'role': user.group, 'quota_act': True,
            'is_active': user.is_active, 'email': user.email,
            'mailboxes_limit': 2, 'mailbox_aliases_limit': 3
        }
        resp = self.ajax_post(
            reverse("admin:account_change", args=[user.id]),
            values, 424
        )
        self.assertEqual(resp, 'Not enough resources')
        self._check_limit('mailboxes', 1, 2)
        self._check_limit('mailbox_aliases', 0, 2)
