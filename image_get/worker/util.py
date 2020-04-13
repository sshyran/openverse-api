import asyncio
import json
import logging as log
import time
import pykafka
import worker.settings as settings
from worker.stats_reporting import StatsManager
from functools import partial
from io import BytesIO
from PIL import Image, UnidentifiedImageError


def kafka_connect():
    try:
        client = pykafka.KafkaClient(hosts=settings.KAFKA_HOSTS)
    except pykafka.exceptions.NoBrokersAvailableError:
        log.info('Retrying Kafka connection. . .')
        time.sleep(3)
        return kafka_connect()
    return client


def parse_message(message):
    decoded = json.loads(str(message.value, 'utf-8'))
    decoded['source'] = decoded['source'].lower()
    return decoded


def thumbnail_image(img: Image):
    img.thumbnail(size=settings.TARGET_RESOLUTION, resample=Image.NEAREST)
    output = BytesIO()
    img.save(output, format="JPEG", quality=30)
    output.seek(0)
    return output


def save_thumbnail_s3(s3_client, img: BytesIO, identifier):
    s3_client.put_object(
        Bucket='cc-image-analysis',
        Key=f'{identifier}.jpg',
        Body=img
    )


async def process_image(persister, session, url, identifier, stats: StatsManager, source, semaphore):
    """
    Get an image, resize it, and persist it.
    :param stats: A StatsManager for recording task statuses.
    :param source: Used to determine rate limit policy. Example: flickr, behance
    :param semaphore: Limits concurrent execution of process_image tasks
    :param identifier: Our identifier for the image at the URL.
    :param persister: The function defining image persistence. It
    should do something like save an image to disk, or upload it to
    S3.
    :param session: An aiohttp client session.
    :param url: The URL of the image.
    """
    async with semaphore:
        loop = asyncio.get_event_loop()
        img_resp = await session.get(url, source)
        if img_resp.status >= 400:
            await stats.record_error(source, code=img_resp.status)
            return
        buffer = BytesIO(await img_resp.read())
        try:
            img = await loop.run_in_executor(None, partial(Image.open, buffer))
        except UnidentifiedImageError:
            await stats.record_error(
                source,
                code="UnidentifiedImageError"
            )
            return
        thumb = await loop.run_in_executor(
            None, partial(thumbnail_image, img)
        )
        await loop.run_in_executor(
            None, partial(persister, img=thumb, identifier=identifier)
        )
        await stats.record_success(source)


async def monitor_task_list(tasks):
    # For computing average requests per second
    num_samples = 0
    resize_rate_sum = 0

    last_time = time.monotonic()
    last_count = 0
    while True:
        now = time.monotonic()
        num_completed = sum([t.done() for t in tasks])
        task_delta = num_completed - last_count
        time_delta = now - last_time
        resize_rate = task_delta / time_delta

        last_time = now
        last_count = num_completed
        if resize_rate > 0:
            resize_rate_sum += resize_rate
            num_samples += 1
            mean = resize_rate_sum / num_samples
            log.info(f'resize_rate_1s={round(resize_rate, 2)}/s, '
                     f'avg_resize_rate={round(mean, 2)}/s, '
                     f'num_completed={num_completed}')
        await asyncio.sleep(1)