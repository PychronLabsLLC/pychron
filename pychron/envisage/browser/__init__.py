__author__ = "ross"

import logging
import time

from pychron.core.progress import progress_loader

_logger = logging.getLogger(__name__)


def progress_bind_records(ans):
    bind_total = [0.0]
    bind_max = [0.0]
    bind_max_id = [None]

    def func(xi, prog, i, n):
        bst = time.time()
        xi.bind()
        bdt = time.time() - bst
        bind_total[0] += bdt
        if bdt > bind_max[0]:
            bind_max[0] = bdt
            bind_max_id[0] = getattr(xi, "record_id", None)

        if prog:
            if i == 0:
                prog.change_message("Loading")
            elif i == n - 1:
                prog.change_message("Finished")
            if prog and i % 25 == 0:
                prog.change_message("Loading {}".format(xi.record_id))
        return xi

    st = time.time()
    ret = progress_loader(ans, func, threshold=100, step=20)
    _logger.debug(
        "progress_bind_records n=%d total=%.3fs bind_total=%.3fs bind_max=%.3fs(%s)",
        len(ret) if ret else 0,
        time.time() - st,
        bind_total[0],
        bind_max[0],
        bind_max_id[0],
    )
    return ret
