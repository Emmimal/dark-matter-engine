# File Upload

## Starting an upload
The client calls POST /uploads with the file name and size. The service returns an upload id and a part size of 5 MB.

## Uploading parts
The client sends each part with PUT /uploads/{id}/parts/{n}. The service stores the part and returns its checksum.

## Completing
The client calls POST /uploads/{id}/complete. The service assembles the parts in order and verifies the total size matches the size declared at the start.

## Size limit
Files larger than 2 GB are rejected at the start of the upload with a 413 response.

## Abandoned uploads
Parts of an upload that has seen no activity for 24 hours are deleted by a nightly cleanup job, and the upload id then returns 404.
