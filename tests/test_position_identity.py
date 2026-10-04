import unittest

from bolsa_abierta.position_identity import membership_id, annotate_memberships


class MembershipIdentityTests(unittest.TestCase):
    def row(self, **changes):
        return dict(id='existing-record-id', specialty='0590006', block='69',
                    list_number='25000010', name='SYNTHETIC NAME', **changes)

    def test_membership_ignores_spelling_but_preserves_course_block_and_scope(self):
        row = self.row()
        identity = membership_id(row, '2026-2027')
        self.assertEqual(identity, membership_id({**row, 'name': 'CORRECTED SPELLING'}, '2026-2027'))
        for changes in ({'block': '70'}, {'specialty': '0590007'}, {'list_number': '25000020'}):
            self.assertNotEqual(identity, membership_id({**row, **changes}, '2026-2027'))
        self.assertNotEqual(identity, membership_id(row, '2027-2028'))

    def test_existing_record_ids_and_award_identity_are_not_silently_reassigned(self):
        rows = [self.row(), {'record_type': 'award', 'id': 'award-fact-id', 'rank': None}]
        result = annotate_memberships(rows, '2026-2027')
        self.assertEqual(result[0]['id'], 'existing-record-id')
        self.assertIn('membership_id', result[0])
        self.assertNotIn('membership_id', result[1])
        self.assertNotIn('membership_id', rows[0])

    def test_membership_has_no_global_person_identity(self):
        with self.assertRaises(ValueError):
            membership_id({'name': 'SYNTHETIC NAME', 'list_number': '25000010'}, '2026-2027')
        with self.assertRaises(ValueError):
            annotate_memberships([self.row(), self.row()], '2026-2027')
