import util

people = {}
people['a'] = 'A';
people['z'] = 'Z';
people['m'] = 'M';

title = 'hi'

title = util.make_html_bold(title) + "  | Number of Votes: " + str(len(people))

print(title)
