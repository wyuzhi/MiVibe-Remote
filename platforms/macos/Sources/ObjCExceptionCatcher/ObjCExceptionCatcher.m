#import "ObjCExceptionCatcher.h"

NSString * _Nullable MiVibeCatchObjectiveCException(
    NS_NOESCAPE void (^block)(void)
) {
    @try {
        block();
        return nil;
    } @catch (NSException *exception) {
        NSString *reason = exception.reason ?: @"No exception reason";
        return [NSString stringWithFormat:@"%@: %@", exception.name, reason];
    }
}
