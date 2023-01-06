#!/usr/bin/env bash

# Desc: Copy new JJ results to remote server using SSH key auth and tarball compression


# To do:
# use unique tarball filenames - unn
# use diff dirs than jj results. at server also - unn
# send only results and errorlog?




set -e
cd /home/joepers/joes_jorbs/


# Get most recent date dir by name
dater=$(ls | sort | tail -n 1)

echo -e \\nSending $dater results to remote server ...


# Create tarball, pv for progress, login to remote host, copy to result dir
tar cz "$dater" | pv | ssh -p 17589 -i /home/joepers/.ssh/id_rsa root@134.122.12.32 'cat | tar xz --warning=no-timestamp -C /home/joe'


echo Files copied to server: $(find $dater/results/ -type f | wc -l)















