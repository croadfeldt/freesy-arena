"""The arena account's uid is set in one place.

Run: python3 -m unittest deploy/image/test_image_account.py

The uid is in the account's definition and in the name of the folder its container unit lives in. The
first draft wrote 1001 in each by hand, which collided with a person's account at the first site that
used the image. Now the Containerfile's CHEESY_UID is the only number and install.sh fills in the rest.
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def read(*parts):
    with open(os.path.join(HERE, *parts)) as handle:
        return handle.read()


class ArenaAccountUid(unittest.TestCase):
    def test_the_containerfile_sets_the_uid_and_hands_it_to_install(self):
        text = read("Containerfile")
        self.assertRegex(text, r"(?m)^ARG CHEESY_UID=\d+$")
        self.assertIn("CHEESY_UID=${CHEESY_UID} /src/deploy/image/install.sh", text)

    def test_the_account_definition_takes_the_uid_from_the_build(self):
        lines = [l for l in read("files", "usr", "lib", "sysusers.d", "freezy.conf").splitlines()
                 if l.startswith("u ")]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split()[:3], ["u", "cheesy", "@CHEESY_UID@"])
        self.assertIn('sed -i "s/@CHEESY_UID@/$uid/" /usr/lib/sysusers.d/freezy.conf', read("install.sh"))

    def test_the_container_unit_folder_is_named_from_the_build(self):
        script = read("install.sh")
        placed = re.findall(r"/etc/containers/systemd/users/([^/\s\"]+)/", script)
        self.assertTrue(placed, "install.sh no longer places the arena's container unit")
        self.assertEqual(set(placed), {"$uid"})

    def test_no_file_in_the_overlay_sits_in_a_folder_named_for_a_uid(self):
        users = os.path.join(HERE, "files", "etc", "containers", "systemd", "users")
        self.assertFalse(os.path.isdir(users) and os.listdir(users),
                         "a unit under files/etc/containers/systemd/users/ fixes the uid by hand")

    def test_install_refuses_a_uid_that_is_taken(self):
        script = read("install.sh")
        self.assertIn('getent passwd "$uid"', script)
        self.assertIn("/usr/lib/sysusers.d", script.split("taken=")[1].split("fi\n")[0])


if __name__ == "__main__":
    unittest.main()
