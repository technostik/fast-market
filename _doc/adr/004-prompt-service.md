in @common add a new service : 'prompt' that will allow unified prompt management.

many commands use internally prompts that can be ovveridden by the user. But each one uses it's own mechanism.

I want a clean, once and for all, service to manage prompt. The goal is to provide a set of subcommands easy to call. The command using them will only have to declare them in click.

for example : 
'skill prompt ...' where we can complet with :

1. create : create a new prompt with and id and a content.
2. delete
3. rename
4. get : just return the content of the prompt
5. list : list all prompts ids for this command
6. set : change prompt content by cli
7. edit : open editor (nano by default) to change the prompt
8. show : list all prompts ids AND content
9. path : show all prompts paths, unless one is specified
10. reset : without id, reset ALL prompts to their default values, or reset only one

All theses commands should support auto-complete.
But for now I want the implementation. The overiden prompts must be stored in the XDG config directory and not in database.
