name: Download Instagram and Upload to Buffer

on:
  workflow_dispatch:
    inputs:
      instagram_url:
        description: 'رابط انستغرام'
        required: true
        type: string

jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          pip install instaloader requests

      - name: Download Instagram Video
        id: download
        env:
          INSTAGRAM_URL: ${{ github.event.inputs.instagram_url }}
        run: |
          python << 'PYTHON_SCRIPT'
          import os
          import sys
          import instaloader
          import glob

          url = os.getenv('INSTAGRAM_URL')
          if not url:
              print("❌ No URL provided")
              sys.exit(1)

          shortcode = None
          if "/reel/" in url:
              shortcode = url.split("/reel/")[1].split("/")[0]
          elif "/p/" in url:
              shortcode = url.split("/p/")[1].split("/")[0]
          
          if not shortcode:
              print(f"❌ Could not extract shortcode from: {url}")
              sys.exit(1)

          print(f"🔍 Fetching post: {shortcode}")

          L = instaloader.Instaloader(
              download_pictures=False,
              download_videos=True,
              download_video_thumbnails=False,
              download_comments=False,
              save_metadata=False,
              dirname_pattern="./downloads",
              filename_pattern="{shortcode}"
          )

          try:
              post = instaloader.Post.from_shortcode(L.context, shortcode)
              
              if not post.is_video:
                  print("❌ Not a video")
                  sys.exit(1)

              print("📥 Downloading video...")
              L.download_post(post, target="./downloads")
              
              files = glob.glob("./downloads/*.mp4")
              if not files:
                  files = glob.glob("./downloads/*")
                  files = [f for f in files if f.endswith('.mp4')]
              
              if not files:
                  print("❌ No video file found")
                  sys.exit(1)

              video_path = files[0]
              caption = post.caption if post.caption else f"Video from Instagram: {shortcode}"
              caption = caption.replace('"', '\\"').replace('\n', ' ')[:280]
              
              with open('/tmp/video_info.txt', 'w') as f:
                  f.write(f"{video_path}\n{caption}")
              print(f"✅ Downloaded: {video_path}")
          except Exception as e:
              print(f"❌ Error: {e}")
              sys.exit(1)
          PYTHON_SCRIPT

      - name: Upload to Cloud (Catbox)
        id: upload
        run: |
          VIDEO_PATH=$(head -n 1 /tmp/video_info.txt)
          echo "Uploading $VIDEO_PATH to Catbox..."
          UPLOAD_RESPONSE=$(curl -s -X POST -F "files[]=@$VIDEO_PATH" https://catbox.moe/user/api.php)
          PUBLIC_URL=$(echo $UPLOAD_RESPONSE | grep -o 'https://files.catbox.moe/[^"]*')
          
          if [ -z "$PUBLIC_URL" ]; then
            echo "❌ Upload failed"
            exit 1
          fi
          
          echo "✅ Uploaded: $PUBLIC_URL"
          echo "public_url=$PUBLIC_URL" >> $GITHUB_OUTPUT

      - name: Upload to Buffer
        env:
          BUFFER_API_TOKEN: ${{ secrets.BUFFER_API_TOKEN }}
          BUFFER_CHANNEL_ID: ${{ secrets.BUFFER_CHANNEL_ID }}
        run: |
          python << 'PYTHON_SCRIPT'
          import os
          import requests

          with open('/tmp/video_info.txt', 'r') as f:
              lines = f.readlines()
              caption = lines[1].strip()
          
          public_url = os.getenv('PUBLIC_URL')
          if not public_url:
              # Fallback if output variable not passed correctly in some envs, read from step output file if needed
              # But in this simple flow, we rely on the previous step setting GITHUB_OUTPUT
              # Let's re-read from a file if needed, but ideally we pass it via env
              pass

          # Re-reading public_url from the output file of previous step is tricky in bash->python bridge without passing env
          # Let's assume we pass it via env in the next step or read from a file created by upload step
          # Simpler: Read from a file created by upload step
          with open('/tmp/public_url.txt', 'r') as f:
              public_url = f.read().strip()

          GRAPHQL_URL = "https://api.buffer.com/v1/graphql"
          CHANNEL_ID = os.getenv('BUFFER_CHANNEL_ID')
          TOKEN = os.getenv('BUFFER_API_TOKEN')

          query = f'''
          mutation CreatePost {{
              createPost(input: {{
                  text: "{caption}",
                  channelId: "{CHANNEL_ID}",
                  schedulingType: automatic,
                  mode: addToQueue,
                  assets: {{
                      video: {{
                          url: "{public_url}"
                      }}
                  }}
              }}) {{
                  ... on PostActionSuccess {{
                      post {{
                          id
                          text
                      }}
                  }}
                  ... on MutationError {{
                      message
                  }}
              }}
          }}
          '''

          headers = {
              "Authorization": f"Bearer {TOKEN}",
              "Content-Type": "application/json"
          }

          response = requests.post(GRAPHQL_URL, json={"query": query}, headers=headers)
          
          if response.status_code == 200:
              result = response.json()
              if "data" in result and "createPost" in result["data"]:
                  post_data = result["data"]["createPost"]
                  if "post" in post_data:
                      print(f"✅ Posted to Buffer: {post_data['post']['id']}")
                  elif "message" in post_data:
                      print(f"❌ Buffer Error: {post_data['message']}")
              else:
                  print(f"❌ Unexpected response: {result}")
          else:
              print(f"❌ HTTP Error: {response.status_code} - {response.text}")
          PYTHON_SCRIPT
